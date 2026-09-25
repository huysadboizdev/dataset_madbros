from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, field_validator

BlockType = Literal["paragraph", "heading", "formula", "table", "list", "skipped_visual", "other"]
ReviewStatus = Literal["unreviewed", "edited", "reviewed_by_user"]

JobState = Literal["CREATED", "RUNNING", "PAUSE_REQUESTED", "PAUSED", "COMPLETED",
                   "COMPLETED_WITH_ERRORS", "CANCELLED", "INTERRUPTED", "FAILED"]
PageState = Literal["PENDING", "RUNNING", "SUCCEEDED", "NEEDS_REVIEW", "FAILED", "INTERRUPTED"]
PageMethod = Literal["ocr", "direct", "ocr_reprocess", "cached", "unknown"]


def _strict_int(v: Any) -> int:
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("page phải là số nguyên 1-based, không nhận bool/float/chuỗi")
    return v


class BlockModel(BaseModel):
    block_id: str
    type: BlockType
    text: Optional[str] = None
    latex: Optional[str] = None
    order: int = 0
    bbox: Optional[List[float]] = None
    confidence: Optional[float] = None

    @field_validator("order")
    @classmethod
    def _order_int(cls, v: Any) -> int:
        return _strict_int(v)


class PageSelectionRequest(BaseModel):
    expression: Optional[str] = None
    from_page: Optional[int] = None
    to_page: Optional[int] = None
    all_pages: bool = False

    @field_validator("all_pages")
    @classmethod
    def _bool_only(cls, v: Any) -> bool:
        if not isinstance(v, bool):
            raise ValueError("all_pages phải là true/false")
        return v


class PageSelectionResponse(BaseModel):
    selected_pages: List[int]
    selected_count: int
    document_page_count: int
    warnings: List[str] = []


class JobCreateRequest(BaseModel):
    document_id: str
    selected_pages: List[int]
    mode: Literal["auto_text_formula"] = "auto_text_formula"
    ocr_again: bool = False
    notes: Optional[Dict[str, str]] = None

    @field_validator("selected_pages")
    @classmethod
    def _pages_strict(cls, v: List[Any]) -> List[int]:
        if not v:
            raise ValueError("Phải chọn ít nhất 1 trang")
        return [_strict_int(p) for p in v]

    @field_validator("ocr_again")
    @classmethod
    def _bool_only(cls, v: Any) -> bool:
        if not isinstance(v, bool):
            raise ValueError("ocr_again phải là true/false")
        return v


class PageRunModel(BaseModel):
    page_no: int
    status: PageState
    method: PageMethod = "unknown"
    attempt: int = 0
    duration_s: Optional[float] = None
    error: Optional[str] = None
    active_revision_id: Optional[str] = None
    review_status: ReviewStatus = "unreviewed"


class JobModel(BaseModel):
    job_id: str
    document_id: str
    document_name: str
    document_page_count: int
    selected_pages: List[int]
    mode: str
    config_hash: str
    status: JobState
    current_page: Optional[int] = None
    succeeded_pages: int = 0
    failed_pages: int = 0
    pending_pages: int = 0
    eta_s: Optional[float] = None
    model_phase: Optional[str] = None
    process_phase: Optional[str] = None
    events: List[Dict[str, Any]] = []
    pages: List[PageRunModel] = []
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class PageResultModel(BaseModel):
    job_id: str
    document_id: str
    pdf_page: int
    printed_page: Optional[int] = None
    status: PageState
    method: PageMethod
    review_status: ReviewStatus
    revision_id: Optional[str] = None
    base_revision_id: Optional[str] = None
    blocks: List[BlockModel] = []
    coordinate_space: Optional[Dict[str, Any]] = None
    issues: List[Dict[str, Any]] = []
    warnings: List[str] = []
    updated_at: Optional[str] = None


class PageEditRequest(BaseModel):
    base_revision_id: str
    blocks: List[BlockModel]
    printed_page: Optional[int] = None


class ReprocessRequest(BaseModel):
    base_revision_id: Optional[str] = None


class ExportRequest(BaseModel):
    format: Literal["md", "json", "zip"] = "zip"
    pages: Optional[List[int]] = None

    @field_validator("pages")
    @classmethod
    def _pages_strict(cls, v: Optional[List[Any]]) -> Optional[List[int]]:
        if v is None:
            return None
        return [_strict_int(p) for p in v]


class ExportModel(BaseModel):
    export_id: str
    job_id: str
    format: str
    included_pages: List[int]
    missing_pages: List[int]
    partial: bool
    filename: str
    created_at: str
    checksum_sha256: Optional[str] = None


class DocumentModel(BaseModel):
    document_id: str
    original_name: str
    size_bytes: int
    sha256: str
    page_count: int
    ingested_at: str
    metadata: Dict[str, Any] = {}
    duplicate: bool = False
