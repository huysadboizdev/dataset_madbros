from __future__ import annotations

"""Exam Builder — chuyển blocks (OcrBlock) → exam object (SOP §4)."""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import jsonschema
from jsonschema import validate

from ..ocr.base import OcrBlock


@dataclass
class ExamOption:
    option_id: str
    text: str


@dataclass
class ExamQuestion:
    question_id: str
    type: str  # single, multi, essay, true_false
    content: str
    context_id: Optional[str]
    options: List[ExamOption]
    correct_option_ids: List[str]
    correct_answer: Optional[str]
    score: float
    difficulty: str
    topic: Optional[str]
    explanation: Optional[str]
    explanation_origin: Optional[str] = None  # SOP §2.2: source | expert_authored | ai_assisted
    source_locator: Optional[str] = None  # SOP §4.1: source_id:page_number:question_index
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExamContext:
    context_id: str
    type: str  # reading_passage, reference_text, data_table, image_description, audio_transcript
    content: str
    language: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExamMetadata:
    subject: str
    grade: int
    duration_minutes: int
    total_score: float
    source_ids: List[str]
    created_at: str
    version: str
    description: Optional[str] = None


@dataclass
class Exam:
    exam_id: str
    metadata: ExamMetadata
    questions: List[ExamQuestion]
    contexts: List[ExamContext] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exam_id": self.exam_id,
            "metadata": {
                "subject": self.metadata.subject,
                "grade": self.metadata.grade,
                "duration_minutes": self.metadata.duration_minutes,
                "total_score": self.metadata.total_score,
                "source_ids": self.metadata.source_ids,
                "created_at": self.metadata.created_at,
                "version": self.metadata.version,
                "description": self.metadata.description,
            },
            "contexts": [
                {
                    "context_id": c.context_id,
                    "type": c.type,
                    "content": c.content,
                    "language": c.language,
                    "metadata": c.metadata,
                }
                for c in self.contexts
            ],
            "questions": [
                {
                    "question_id": q.question_id,
                    "type": q.type,
                    "content": q.content,
                    "context_id": q.context_id,
                    "options": [
                        {"option_id": o.option_id, "text": o.text}
                        for o in q.options
                    ],
                    "correct_option_ids": q.correct_option_ids,
                    "correct_answer": q.correct_answer,
                    "score": q.score,
                    "difficulty": q.difficulty,
                    "topic": q.topic,
                    "explanation": q.explanation,
                    "explanation_origin": q.explanation_origin,
                    "source_locator": q.source_locator,
                    "metadata": q.metadata,
                }
                for q in self.questions
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class ExamBuilder:
    """Xây dựng Exam từ danh sách OcrBlock (đã qua cleaning + context_id)."""

    SCHEMA_PATH = Path(__file__).parent / "schema" / "exam.schema.json"
    _schema: Optional[Dict] = None

    def __init__(self):
        self._load_schema()

    def _load_schema(self) -> None:
        if ExamBuilder._schema is None:
            with open(ExamBuilder.SCHEMA_PATH, "r", encoding="utf-8") as f:
                ExamBuilder._schema = json.load(f)

    def validate(self, exam_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate exam dict against JSON Schema.
        Returns (is_valid, errors_list).
        """
        try:
            validate(instance=exam_dict, schema=ExamBuilder._schema)
            return True, []
        except jsonschema.ValidationError as e:
            return False, [f"{e.json_path}: {e.message}"]
        except jsonschema.SchemaError as e:
            return False, [f"Schema error: {e.message}"]

    def build_from_blocks(
        self,
        blocks: List[OcrBlock],
        subject: str,
        grade: int,
        duration_minutes: int,
        total_score: float,
        source_ids: List[str],
        created_at: str,
        version: str = "1.0.0",
        description: Optional[str] = None,
    ) -> Exam:
        """Tự động xây dựng Exam từ blocks (heuristic).

        Logic:
        - Blocks có context_id → gom thành contexts + questions
        - Heading → section/topic
        - Paragraph + formula → content
        - Table → options hoặc data_table context
        - Cần review thủ công sau khi build tự động
        """
        # Tách contexts và questions từ blocks
        contexts, question_blocks = self._split_contexts_and_questions(blocks)

        # Build contexts
        exam_contexts = []
        for ctx_id, ctx_blocks in contexts.items():
            content = "\n\n".join(b.text or "" for b in ctx_blocks if b.text)
            if content.strip():
                exam_contexts.append(ExamContext(
                    context_id=ctx_id,
                    type="reading_passage" if grade in (10, 11, 12) and subject == "ENG" else "reference_text",
                    content=content,
                    language="en" if subject == "ENG" else "vi",
                    metadata={"source_blocks": [b.order for b in ctx_blocks]}
                ))

        # Build questions (heuristic - cần review)
        questions = self._heuristic_build_questions(question_blocks, exam_contexts)

        # Tính total_score từ questions nếu chưa có
        calc_score = sum(q.score for q in questions) if questions else total_score

        metadata = ExamMetadata(
            subject=subject,
            grade=grade,
            duration_minutes=duration_minutes,
            total_score=calc_score,
            source_ids=source_ids,
            created_at=created_at,
            version=version,
            description=description,
        )

        exam_id = f"EXAM_{subject}_G{grade:02d}_{created_at[:4]}_{uuid.uuid4().hex[:4].upper()}"

        return Exam(
            exam_id=exam_id,
            metadata=metadata,
            questions=questions,
            contexts=exam_contexts,
        )

    def _split_contexts_and_questions(
        self, blocks: List[OcrBlock]
    ) -> Tuple[Dict[str, List[OcrBlock]], List[OcrBlock]]:
        """Tách blocks thành contexts (có context_id) và questions (còn lại)."""
        contexts: Dict[str, List[OcrBlock]] = {}
        questions: List[OcrBlock] = []

        for b in blocks:
            ctx_id = getattr(b, "metadata", {}).get("context_id") if isinstance(getattr(b, "metadata", {}), dict) else None
            if ctx_id:
                contexts.setdefault(ctx_id, []).append(b)
            else:
                questions.append(b)

        return contexts, questions

    def _heuristic_build_questions(
        self, blocks: List[OcrBlock], contexts: List[ExamContext]
    ) -> List[ExamQuestion]:
        """Heuristic: gom blocks thành câu hỏi.
        CẦN REVIEW THỦ CÔNG - chỉ tạo khung."""
        questions: List[ExamQuestion] = []
        current_question: Optional[Dict] = None

        for b in blocks:
            if b.type == "heading":
                # Heading mới → câu hỏi mới
                if current_question:
                    questions.append(self._finalize_question(current_question, contexts))
                current_question = {
                    "topic": b.text,
                    "content_parts": [],
                    "options": [],
                    "type": "single",  # default
                    "source_blocks": [b],
                }
            elif b.type in ("paragraph", "formula"):
                if current_question:
                    text = b.latex if b.type == "formula" else b.text
                    if text:
                        current_question["content_parts"].append(text)
                    current_question.setdefault("source_blocks", []).append(b)
                else:
                    # Không có heading trước → tạo câu hỏi mới
                    current_question = {
                        "topic": None,
                        "content_parts": [b.latex if b.type == "formula" else b.text],
                        "options": [],
                        "type": "single",
                        "source_blocks": [b],
                    }
            elif b.type == "table":
                # Bảng có thể là options (single/multi) hoặc data_table context
                if current_question and not current_question["options"]:
                    # Parse table as options
                    opts = self._parse_table_as_options(b.text or "")
                    if opts:
                        current_question["options"] = opts
                        current_question["type"] = "multi" if len(opts) > 4 else "single"
                    current_question.setdefault("source_blocks", []).append(b)
                else:
                    # Bảng độc lập → context data_table
                    pass
            # skipped_visual, visual_label: bỏ qua hoặc gán metadata

        # Finalize last question
        if current_question:
            questions.append(self._finalize_question(current_question, contexts))

        return questions

    def _parse_table_as_options(self, markdown_table: str) -> List[ExamOption]:
        """Parse Markdown table thành options (A, B, C, D...)."""
        options = []
        lines = [l.strip() for l in markdown_table.split("\n") if l.strip()]
        if len(lines) < 3:  # header + divider + ít nhất 1 row
            return options

        # Skip header and divider
        for i, line in enumerate(lines[2:]):
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if len(cells) >= 2:
                # First cell = option_id/label, rest = text
                opt_id = f"opt_{uuid.uuid4().hex[:8]}"
                options.append(ExamOption(option_id=opt_id, text=" | ".join(cells)))
            elif len(cells) == 1:
                opt_id = f"opt_{uuid.uuid4().hex[:8]}"
                options.append(ExamOption(option_id=opt_id, text=cells[0]))

        return options

    def _finalize_question(
        self, qdata: Dict, contexts: List[ExamContext]
    ) -> ExamQuestion:
        """Hoàn thiện question từ heuristic data."""
        qid = f"q_{uuid.uuid4().hex[:12]}"
        content = "\n\n".join(qdata["content_parts"])
        options = qdata["options"]

        # Determine type based on options
        qtype = qdata["type"]
        if not options:
            qtype = "essay"

        correct_ids = []
        if qtype in ("single", "multi", "true_false") and options:
            # Default: first option correct (CẦN SỬA THỦ CÔNG)
            correct_ids = [options[0].option_id]

        return ExamQuestion(
            question_id=qid,
            type=qtype,
            content=content,
            context_id=None,  # Cần gán thủ công
            options=options,
            correct_option_ids=correct_ids,
            correct_answer=None if qtype != "essay" else "Cần điền lời giải mẫu",
            score=1.0,
            difficulty="medium",
            topic=qdata["topic"],
            explanation=None,
            source_locator=None,  # Cần gán thủ công từ nguồn gốc
            metadata={
                "source_block_orders": [i for i, _ in enumerate(qdata.get("source_blocks", []))],
                "source_block_types": [b.type for b in qdata.get("source_blocks", [])],
            },
        )


def load_exam_from_json(path: Union[str, Path]) -> Exam:
    """Load Exam từ file JSON."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Reconstruct Exam object
    return _dict_to_exam(data)


def _dict_to_exam(data: Dict[str, Any]) -> Exam:
    metadata = ExamMetadata(**data["metadata"])
    contexts = [ExamContext(**c) for c in data.get("contexts", [])]
    questions = []
    for q in data["questions"]:
        options = [ExamOption(**opt) for opt in q.get("options", [])]
        q_copy = {**q, "options": options}
        questions.append(ExamQuestion(**q_copy))
    return Exam(
        exam_id=data["exam_id"],
        metadata=metadata,
        questions=questions,
        contexts=contexts,
    )