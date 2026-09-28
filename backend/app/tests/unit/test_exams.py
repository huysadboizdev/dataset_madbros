from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.app.exams.builder import (
    Exam,
    ExamBuilder,
    ExamQuestion,
    ExamContext,
    ExamOption,
    ExamMetadata,
    load_exam_from_json,
)
from backend.app.exams.validate import ExamValidator, validate_exam_file
from backend.app.exams.export import ExamExporter
from backend.app.ocr.base import OcrBlock


class TestExamSchema:
    def test_schema_loads(self):
        builder = ExamBuilder()
        assert builder._schema is not None
        assert "properties" in builder._schema

    def test_valid_exam_passes_schema(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        ok, errors = builder.validate(exam.to_dict())
        assert ok, f"Schema validation failed: {errors}"
        assert errors == []

    def test_source_locator_in_to_dict(self):
        """SOP §4.1: source_locator được serialize trong to_dict."""
        exam = _make_minimal_exam()
        d = exam.to_dict()
        assert "source_locator" in d["questions"][0]
        assert "source_locator" in d["questions"][1]
        assert d["questions"][1]["source_locator"] == "MATH_G10_2026_0001:23:1"

    def test_source_locator_optional(self):
        """source_locator có thể null (chưa gán nguồn gốc)."""
        q = ExamQuestion(
            question_id="q_test",
            type="single",
            content="Test",
            context_id=None,
            options=[],
            correct_option_ids=[],
            correct_answer="x",
            score=1.0,
            difficulty="medium",
            topic="math",
            explanation="test",
            source_locator=None,
        )
        builder = ExamBuilder()
        ok, errors = builder.validate(builder._schema)
        # source_locator is optional, not required

    def test_invalid_exam_fails_schema(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        # Remove required field
        data = exam.to_dict()
        del data["metadata"]["subject"]
        ok, errors = builder.validate(data)
        assert not ok
        assert len(errors) > 0
        assert any("subject" in e for e in errors)


class TestExamBuilder:
    def test_build_from_blocks_creates_exam(self):
        blocks = _make_sample_blocks()
        builder = ExamBuilder()
        exam = builder.build_from_blocks(
            blocks=blocks,
            subject="MATH",
            grade=10,
            duration_minutes=90,
            total_score=10.0,
            source_ids=["MATH_G10_2026_0001"],
            created_at="2026-09-27T10:00:00Z",
        )
        assert isinstance(exam, Exam)
        assert exam.exam_id.startswith("EXAM_MATH_G10_2026_")
        assert exam.metadata.subject == "MATH"
        assert exam.metadata.grade == 10
        assert len(exam.questions) > 0

    def test_build_exam_has_valid_schema(self):
        blocks = _make_sample_blocks()
        builder = ExamBuilder()
        exam = builder.build_from_blocks(
            blocks=blocks,
            subject="ENG",
            grade=11,
            duration_minutes=60,
            total_score=10.0,
            source_ids=["ENG_G11_2025_0001"],
            created_at="2026-09-27T10:00:00Z",
        )
        ok, errors = builder.validate(exam.to_dict())
        assert ok, f"Built exam failed validation: {errors}"


class TestExamValidator:
    def test_valid_exam_passes(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert ok, f"Valid exam failed: {[i.message for i in issues]}"

    def test_duplicate_question_id_fails(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        # Duplicate question_id
        exam.questions[1].question_id = exam.questions[0].question_id
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "DUPLICATE_QUESTION_ID" for i in issues)

    def test_invalid_correct_option_ref_fails(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        # Point to non-existent option
        exam.questions[0].correct_option_ids = ["opt_nonexistent"]
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "INVALID_CORRECT_OPTION_REF" for i in issues)

    def test_invalid_context_ref_fails(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        exam.questions[0].context_id = "ctx_nonexistent"
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "INVALID_CONTEXT_REF" for i in issues)

    def test_score_mismatch_fails(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        exam.metadata.total_score = 999.0  # Mismatch
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "SCORE_MISMATCH" for i in issues)

    def test_single_question_rules(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        q = exam.questions[0]
        q.type = "single"
        q.options = [ExamOption(option_id="opt_a", text="A")]
        q.correct_option_ids = ["opt_a"]
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "SINGLE_INSUFFICIENT_OPTIONS" for i in issues)

    def test_multi_question_rules(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        q = exam.questions[0]
        q.type = "multi"
        q.options = [ExamOption(option_id="opt_a", text="A"), ExamOption(option_id="opt_b", text="B")]
        q.correct_option_ids = ["opt_a"]
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "MULTI_INSUFFICIENT_OPTIONS" for i in issues)
        assert any(i.code == "MULTI_INSUFFICIENT_CORRECT" for i in issues)

    def test_essay_question_rules(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        q = exam.questions[0]
        q.type = "essay"
        q.options = [ExamOption(option_id="opt_a", text="A")]  # Should not have options
        q.correct_answer = None  # Should have correct_answer
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "ESSAY_SHOULD_NOT_HAVE_OPTIONS" for i in issues)
        assert any(i.code == "ESSAY_MISSING_CORRECT_ANSWER" for i in issues)

    def test_correct_options_subset_check(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        q = exam.questions[0]
        q.correct_option_ids = ["opt_a", "opt_nonexistent"]
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        assert not ok
        assert any(i.code == "CORRECT_OPTIONS_NOT_SUBSET" for i in issues)

    def test_placeholder_detection(self):
        builder = ExamBuilder()
        exam = _make_minimal_exam()
        exam.questions[0].content = "Câu hỏi với ... placeholder"
        validator = ExamValidator(builder)
        ok, issues = validator.validate(exam)
        # Warning, not error
        assert ok
        assert any(i.code == "PLACEHOLDER_DETECTED" for i in issues)


class TestExamExport:
    def test_export_json(self):
        exam = _make_minimal_exam()
        exporter = ExamExporter(exam)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "exam.json"
            exporter.export_json(path)
            assert path.exists()
            # Verify can load back
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert data["exam_id"] == exam.exam_id
            assert "exported_at" in data

    def test_export_markdown(self):
        exam = _make_minimal_exam()
        exporter = ExamExporter(exam)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "exam.md"
            exporter.export_markdown(path)
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert exam.exam_id in content
            assert "CÂU HỎI" in content

    def test_export_markdown_with_answers(self):
        exam = _make_minimal_exam()
        exporter = ExamExporter(exam)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "exam_teacher.md"
            exporter.export_markdown(path, include_answers=True)
            content = path.read_text(encoding="utf-8")
            assert "ĐÁP ÁN ĐÚNG" in content


class TestExamLoadSave:
    def test_load_exam_from_json(self):
        exam = _make_minimal_exam()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "exam.json"
            exam.export_json = lambda p: ExamExporter(exam).export_json(p)
            exporter = ExamExporter(exam)
            exporter.export_json(path)
            loaded = load_exam_from_json(path)
            assert loaded.exam_id == exam.exam_id
            assert len(loaded.questions) == len(exam.questions)
            assert len(loaded.contexts) == len(exam.contexts)


def _make_sample_blocks() -> List[OcrBlock]:
    """Tạo sample blocks cho test."""
    return [
        OcrBlock(type="heading", text="Phần Đại số", latex=None, bbox=None, confidence=0.9, order=0),
        OcrBlock(type="paragraph", text="Cho phương trình bậc hai: $x^2 - 5x + 6 = 0$", latex=None, bbox=None, confidence=0.9, order=1),
        OcrBlock(type="formula", text=None, latex="x^2 - 5x + 6 = 0", bbox=None, confidence=0.95, order=2),
        OcrBlock(type="paragraph", text="Tìm nghiệm của phương trình.", latex=None, bbox=None, confidence=0.9, order=3),
        OcrBlock(type="heading", text="Phần Hình học", latex=None, bbox=None, confidence=0.9, order=4),
        OcrBlock(type="paragraph", text="Tam giác ABC có AB = AC. Chứng minh đường cao AD vuông góc BC.", latex=None, bbox=None, confidence=0.9, order=5),
    ]


def _make_minimal_exam() -> Exam:
    """Tạo exam tối thiểu hợp lệ cho test."""
    metadata = ExamMetadata(
        subject="MATH",
        grade=10,
        duration_minutes=90,
        total_score=3.0,
        source_ids=["MATH_G10_2026_0001"],
        created_at="2026-09-27T10:00:00Z",
        version="1.0.0",
    )
    contexts = [
        ExamContext(
            context_id="ctx_abcdef123456",
            type="reference_text",
            content="Định lý Pythagoras: $a^2 + b^2 = c^2$",
            language="vi",
        )
    ]
    questions = [
        ExamQuestion(
            question_id="q_abcdef123456",
            type="single",
            content="Cho tam giác vuông ABC, прямоугольный tại A. AB = 3, AC = 4. Tính BC.",
            context_id="ctx_abcdef123456",
            options=[
                ExamOption(option_id="opt_00000001", text="5"),
                ExamOption(option_id="opt_00000002", text="7"),
                ExamOption(option_id="opt_00000003", text="12"),
                ExamOption(option_id="opt_00000004", text="25"),
            ],
            correct_option_ids=["opt_00000001"],
            correct_answer=None,
            score=1.0,
            difficulty="easy",
            topic="Định lý Pythagoras",
            explanation="Áp dụng định lý Pythagoras: $BC^2 = AB^2 + AC^2 = 9 + 16 = 25 \\Rightarrow BC = 5$",
            explanation_origin="source",
            source_locator="MATH_G10_2026_0001:15:0",
            metadata={},
        ),
        ExamQuestion(
            question_id="q_abcdef123457",
            type="multi",
            content="Chọn các phát biểu đúng về tam giác:",
            context_id=None,
            options=[
                ExamOption(option_id="opt_00000011", text="Tổng 3 góc = 180 độ"),
                ExamOption(option_id="opt_00000012", text="Có 2 góc vuông"),
                ExamOption(option_id="opt_00000013", text="Đường cao luôn nằm trong tam giác"),
                ExamOption(option_id="opt_00000014", text="Tam giác đều có 3 góc 60 độ"),
            ],
            correct_option_ids=["opt_00000011", "opt_00000014"],
            correct_answer=None,
            score=2.0,
            difficulty="medium",
            topic="Tính chất tam giác",
            explanation="Tổng 3 góc tam giác = 180°. Tam giác không thể có 2 góc vuông. Đường cao tam giác tù có thể nằm ngoài. Tam giác đều có 3 góc 60°.",
            explanation_origin="source",
            source_locator="MATH_G10_2026_0001:23:1",
            metadata={},
        ),
    ]
    return Exam(
        exam_id="EXAM_MATH_G10_2026_ABCD",
        metadata=metadata,
        questions=questions,
        contexts=contexts,
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])