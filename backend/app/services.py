import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
import fitz
from PIL import Image
import pytesseract

from .config import (
    MAX_DOCUMENT_PAGES,
    MAX_PAGE_DIMENSION_POINTS,
    TESSERACT_CMD,
    UPLOAD_FOLDER,
    env_or_default,
)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

from .ai_service import AIService
from .document_intelligence import derive_intelligence_fields, normalize_language_label
from .entity_validation import (
    validate_explanatory_text,
    validate_extracted_entities,
    validate_important_dates,
    validate_intelligence_signals,
)
from .models import Document, DocumentAIAnalysis
from .priority_engine import LEVEL_ORDER
from .providers.provider_factory import get_ai_provider
from .document_processing import DocumentProcessingOrchestrator, is_text_truncated_for_analysis

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

UPLOAD_ROOT = Path(UPLOAD_FOLDER).resolve()

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
MAX_UPLOAD_SIZE_BYTES = int(env_or_default("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._ \-]")


def _sanitize_original_filename(filename: str) -> str:
    """Reduce a client-supplied filename to a safe, display-only value (never used as a path)."""
    name = os.path.basename((filename or "").replace("\x00", ""))
    name = _UNSAFE_FILENAME_CHARS.sub("_", name).strip().strip(".")
    return name[:255] if name else "upload"


def _validate_upload_extension(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file extension '{ext or '(none)'}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}"
            ),
        )
    return ext


def _validate_pdf_content(file_path: Path) -> None:
    """Reject files with a .pdf extension whose content is not actually a
    valid, parseable PDF (fake content, wrong format, or corrupt/truncated
    data). Cleans up the stored file on rejection, same as the other upload
    validation steps."""
    try:
        # Read into memory rather than fitz.open(path): opening by path can
        # leave the OS-level file handle held past a failed parse on
        # Windows, which would make the unlink() below fail with a
        # PermissionError.
        pdf_bytes = file_path.read_bytes()
        pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

    try:
        if not pdf_doc.is_pdf:
            file_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")
    finally:
        pdf_doc.close()


def save_document(file: UploadFile, db: Session, owner_id: int) -> Document:
    original_name = file.filename or ""
    ext = _validate_upload_extension(original_name)
    safe_display_name = _sanitize_original_filename(original_name)

    # Storage name is always a generated UUID + validated extension, so the
    # client-supplied filename never reaches the filesystem as a path.
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = (UPLOAD_ROOT / stored_name).resolve()

    if UPLOAD_ROOT not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename.")

    size = 0
    try:
        with open(file_path, "wb") as buffer:
            while True:
                chunk = file.file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File exceeds maximum allowed size of {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.",
                    )
                buffer.write(chunk)
    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise

    if size == 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if ext == ".pdf":
        _validate_pdf_content(file_path)

    document = Document(
        filename=safe_display_name,
        filepath=str(file_path),
        status="uploaded",
        owner_id=owner_id,
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document


def _validate_page_limits(doc: fitz.Document) -> None:
    """Rejects a document whose page count or per-page dimensions could turn
    text/OCR extraction into an unbounded CPU/memory sink - a small file on
    disk (MAX_UPLOAD_SIZE_MB doesn't help here) can still declare thousands
    of pages or an enormous page/MediaBox size. Applies to both PDFs
    (page_count > 1) and images (fitz opens a raster image as a single-page
    "document", so this also bounds a maliciously huge image's pixel
    dimensions before get_pixmap() would allocate a buffer for it)."""
    if doc.page_count > MAX_DOCUMENT_PAGES:
        raise HTTPException(
            status_code=413,
            detail=f"Document has too many pages ({doc.page_count}); the limit is {MAX_DOCUMENT_PAGES}.",
        )

    for page in doc:
        if page.rect.width > MAX_PAGE_DIMENSION_POINTS or page.rect.height > MAX_PAGE_DIMENSION_POINTS:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Page {page.number + 1} is too large "
                    f"({page.rect.width:.0f}x{page.rect.height:.0f}); "
                    f"the limit is {MAX_PAGE_DIMENSION_POINTS}x{MAX_PAGE_DIMENSION_POINTS}."
                ),
            )


def extract_text_with_ocr(filepath: str) -> str:
    try:
        doc = fitz.open(filepath)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Uploaded file could not be read for OCR processing.",
        ) from exc

    try:
        _validate_page_limits(doc)
        pages_text = []
        for page in doc:
            pix = page.get_pixmap(alpha=False)
            mode = "RGB" if pix.n >= 3 else "L"
            image = Image.frombytes(mode, [pix.width, pix.height], pix.samples)
            if mode == "L":
                image = image.convert("RGB")
            page_text = pytesseract.image_to_string(image)
            if page_text:
                pages_text.append(page_text)
    except pytesseract.TesseractNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="OCR is not available on this server (Tesseract is not installed or misconfigured).",
        ) from exc
    finally:
        doc.close()

    return "\n".join(pages_text)


def _ensure_document_analyzed(document: Document, db: Session) -> dict:
    # Invariant: this takes an already-fetched Document, not an id, and does
    # no ownership check of its own - every caller must have already fetched
    # `document` scoped to the requesting owner_id (see analyze_document_by_id
    # / analyze_document_ai_by_id). A new caller that fetches a Document
    # without an owner_id filter and passes it here breaks that guarantee.
    if document.status == "analyzed" and document.text is not None and document.character_count is not None:
        return {
            "filename": document.filename,
            "characters": document.character_count,
            "text": document.text[:1000],
        }

    if not os.path.exists(document.filepath):
        raise HTTPException(status_code=404, detail="Uploaded file not found on disk")

    try:
        doc = fitz.open(document.filepath)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Uploaded file could not be read as a valid document.",
        ) from exc

    try:
        _validate_page_limits(doc)
        text = ""
        for page in doc:
            text += page.get_text()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Uploaded file could not be read as a valid document.",
        ) from exc
    finally:
        doc.close()

    meaningful_text = text.strip()
    if meaningful_text:
        document.text = text
        document.character_count = len(text)
        document.status = "analyzed"
    else:
        ocr_text = extract_text_with_ocr(document.filepath)
        meaningful_ocr_text = ocr_text.strip()
        if meaningful_ocr_text:
            document.text = ocr_text
            document.character_count = len(ocr_text)
            document.status = "analyzed"
        else:
            document.text = ""
            document.character_count = 0
            document.status = "ocr_required"

    db.add(document)
    db.commit()
    db.refresh(document)

    return {
        "filename": document.filename,
        "characters": document.character_count,
        "text": document.text[:1000],
    }


def analyze_document(filename: str, db: Session, owner_id: int) -> dict:
    # Deprecated: filename is not unique, so this returns whichever matching
    # document the caller most recently uploaded. /analyze/id/{document_id}
    # is the canonical, precise lookup - kept only for backward compatibility.
    document = (
        db.query(Document)
        .filter(Document.filename == filename, Document.owner_id == owner_id)
        .order_by(Document.id.desc())
        .first()
    )

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return _ensure_document_analyzed(document, db)


def analyze_document_by_id(document_id: int, db: Session, owner_id: int) -> dict:
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.owner_id == owner_id)
        .first()
    )

    # 404 for both "no such document" and "exists but belongs to someone
    # else" - a 403 would leak which document IDs exist to a user probing
    # IDs that aren't theirs (IDOR/enumeration).
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return _ensure_document_analyzed(document, db)


def _serialize_document_intelligence(document: Document) -> dict:
    # "classified_document_type", not "document_type": the AI-analysis
    # response already carries the LLM's free-form document_type label
    # (DocumentAIAnalysis.document_type) under that key - this is the
    # separate, deterministic-taxonomy-facing value the priority engine
    # produced (see document_intelligence.py), and colliding the two under
    # one key would silently drop whichever was assigned second.
    return {
        "sender_category": document.sender_category,
        "sender_institution": document.sender_institution,
        "classified_document_type": document.document_type,
        "priority_level": document.priority_level,
        "priority_reasoning": document.priority_reasoning,
        "deadline_raw_text": document.deadline_raw_text,
        "deadline_type": document.deadline_type,
        "deadline_estimated_date": (
            document.deadline_estimated_date.isoformat() if document.deadline_estimated_date else None
        ),
        "deadline_certainty": document.deadline_certainty,
        "requires_action": document.requires_action,
        "action_summary": document.action_summary,
        "effective_date": document.effective_date.isoformat() if document.effective_date else None,
        "text_truncated": is_text_truncated_for_analysis(document.character_count),
        "original_character_count": (
            document.character_count
            if is_text_truncated_for_analysis(document.character_count)
            else None
        ),
    }


def _serialize_completed_analysis(analysis: DocumentAIAnalysis, document: Document) -> dict:
    return {
        "analysis_id": analysis.id,
        "document_id": analysis.document_id,
        "provider": analysis.provider,
        "model": analysis.model,
        "status": analysis.status,
        "document_type": analysis.document_type,
        "language": normalize_language_label(analysis.language),
        "summary": analysis.summary,
        "turkish_explanation": analysis.turkish_explanation,
        "important_dates": json.loads(analysis.important_dates) if analysis.important_dates else [],
        "extracted_entities": json.loads(analysis.extracted_entities) if analysis.extracted_entities else [],
        "error_message": analysis.error_message,
        **_serialize_document_intelligence(document),
    }


def analyze_document_ai_by_id(
    document_id: int, db: Session, owner_id: int, force: bool = False
) -> dict:
    document = (
        db.query(Document)
        .filter(Document.id == document_id, Document.owner_id == owner_id)
        .first()
    )

    # 404 for both "no such document" and "belongs to someone else" - see
    # analyze_document_by_id for why (avoids IDOR/enumeration via 403).
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Reuse a previously completed analysis instead of re-calling the AI
    # provider, unless force=True (user-triggered re-analyze - e.g. after a
    # taxonomy/prompt change, or to retry a stale result). Failed analyses
    # are always excluded from reuse so they remain retryable regardless of
    # force. Safe without its own owner_id filter: `document` above is
    # already scoped to the requesting owner, so anything keyed off
    # document.id inherits that scope.
    #
    # force=True does not skip anything below this point - it still calls
    # the real AI provider and inserts a new DocumentAIAnalysis row exactly
    # like a first-time analysis. There is no usage-limit system yet, but
    # when one exists, gating/counting it at the provider-call point below
    # will already cover force-reanalyze for free, since this path is
    # identical to a normal analysis from here on.
    existing_analysis = (
        db.query(DocumentAIAnalysis)
        .filter(
            DocumentAIAnalysis.document_id == document.id,
            DocumentAIAnalysis.status == "completed",
        )
        .order_by(DocumentAIAnalysis.id.desc())
        .first()
    )
    if existing_analysis is not None and not force:
        return _serialize_completed_analysis(existing_analysis, document)

    if not document.text or not document.text.strip():
        _ensure_document_analyzed(document, db)

    try:
        provider = get_ai_provider()
    except Exception as exc:
        analysis_record = DocumentAIAnalysis(
            document_id=document.id,
            provider="unknown",
            model="unknown",
            status="failed",
            raw_response=json.dumps({}),
            error_message=str(exc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(analysis_record)
        db.commit()
        db.refresh(analysis_record)

        raise HTTPException(
            status_code=503,
            detail="AI provider is not available. Please check the server configuration.",
        )

    orchestrator = DocumentProcessingOrchestrator(provider)
    analysis_result = orchestrator.run(document.text or "")

    # Deterministic safety net: drop any code/number/date entity whose value
    # cannot be verified against the source text, before it is persisted or
    # returned. See entity_validation.py for the verification rules.
    analysis_result.extracted_entities = validate_extracted_entities(
        analysis_result.extracted_entities, document.text or ""
    )
    analysis_result.important_dates = validate_important_dates(
        analysis_result.important_dates, document.text or ""
    )
    # summary/turkish_explanation get no structured counterpart to check
    # against (unlike deadline_raw_text/document_date/effective_date/
    # payment_requested below) and are produced by every provider
    # regardless of whether it populates document_intelligence.SIGNAL_KEYS
    # at all - see entity_validation.validate_explanatory_text.
    analysis_result.summary = validate_explanatory_text(analysis_result.summary, document.text or "")
    analysis_result.turkish_explanation = validate_explanatory_text(
        analysis_result.turkish_explanation, document.text or ""
    )

    status = "failed" if analysis_result.error_message else "completed"
    raw_response = analysis_result.raw_response or {}
    if not isinstance(raw_response, dict):
        raw_response = {"raw_response": raw_response}

    analysis_record = DocumentAIAnalysis(
        document_id=document.id,
        provider=provider.provider_name,
        model=provider.model_name,
        status=status,
        document_type=analysis_result.document_type,
        language=analysis_result.language,
        summary=analysis_result.summary,
        turkish_explanation=analysis_result.turkish_explanation,
        important_dates=json.dumps(analysis_result.important_dates or []),
        extracted_entities=json.dumps(analysis_result.extracted_entities or []),
        raw_response=json.dumps(raw_response),
        error_message=analysis_result.error_message,
        completed_at=datetime.now(timezone.utc),
    )

    db.add(analysis_record)
    db.commit()
    db.refresh(analysis_record)

    # Document Intelligence post-processing (priority/deadline engines).
    # Must never take the analyze pipeline down: derive_intelligence_fields
    # already degrades to safe defaults on missing/malformed signals or a
    # failed LLM analysis, and a DB error here is swallowed too, so the AI
    # analysis result computed above is still returned/raised normally.
    try:
        # raw_response is persisted above unmodified (true audit trail of
        # what the LLM returned); the deterministic engines only ever see
        # this separately verified copy, so a hallucinated date or invented
        # payment demand cannot reach deadline_engine/priority_engine or
        # the reader - see entity_validation.validate_intelligence_signals.
        verified_signals = validate_intelligence_signals(raw_response, document.text or "")
        text_truncated = is_text_truncated_for_analysis(document.character_count)
        intelligence_fields = derive_intelligence_fields(verified_signals, text_truncated=text_truncated)
        for field_name, field_value in intelligence_fields.items():
            setattr(document, field_name, field_value)
        db.add(document)
        db.commit()
    except Exception:
        db.rollback()

    response = {
        "analysis_id": analysis_record.id,
        "document_id": analysis_record.document_id,
        "provider": analysis_record.provider,
        "model": analysis_record.model,
        "status": analysis_record.status,
        "document_type": analysis_record.document_type,
        "language": normalize_language_label(analysis_record.language),
        "summary": analysis_record.summary,
        "turkish_explanation": analysis_record.turkish_explanation,
        "important_dates": analysis_result.important_dates or [],
        "extracted_entities": analysis_result.extracted_entities or [],
        "error_message": analysis_record.error_message,
        **_serialize_document_intelligence(document),
    }

    if analysis_result.error_message:
        raise HTTPException(status_code=502, detail=analysis_result.error_message)

    return response


def _serialize_document_summary(document: Document) -> dict:
    return {
        "id": document.id,
        "filename": document.filename,
        "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None,
        "status": document.status,
        "sender_category": document.sender_category,
        "sender_institution": document.sender_institution,
        "document_type": document.document_type,
        "priority_level": document.priority_level,
        "priority_reasoning": document.priority_reasoning,
        "deadline_type": document.deadline_type,
        "deadline_estimated_date": (
            document.deadline_estimated_date.isoformat() if document.deadline_estimated_date else None
        ),
        "deadline_certainty": document.deadline_certainty,
        "requires_action": document.requires_action,
        "action_summary": document.action_summary,
        "effective_date": document.effective_date.isoformat() if document.effective_date else None,
        "text_truncated": is_text_truncated_for_analysis(document.character_count),
        "original_character_count": (
            document.character_count
            if is_text_truncated_for_analysis(document.character_count)
            else None
        ),
    }


def list_documents(db: Session, owner_id: int, priority: Optional[str] = None) -> List[dict]:
    if priority is not None and priority not in LEVEL_ORDER:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority '{priority}'. Must be one of: {', '.join(LEVEL_ORDER)}.",
        )

    query = db.query(Document).filter(Document.owner_id == owner_id)
    if priority is not None:
        query = query.filter(Document.priority_level == priority)
    documents = query.all()

    # Highest severity first; within the same level, the soonest/most
    # certain deadline first, with no-known-deadline documents sorted last.
    # Sorted in Python rather than a SQL ORDER BY: priority_level is a
    # string column with no alphabetical severity order, and this keeps
    # the ranking logic in the one place that already owns it
    # (priority_engine.LEVEL_ORDER) instead of duplicating it as a SQL
    # CASE expression.
    def sort_key(doc: Document):
        level_rank = LEVEL_ORDER.index(doc.priority_level) if doc.priority_level in LEVEL_ORDER else -1
        deadline_date = doc.deadline_estimated_date or datetime.max
        return (-level_rank, deadline_date)

    documents.sort(key=sort_key)

    return [_serialize_document_summary(doc) for doc in documents]


def get_documents_summary(db: Session, owner_id: int) -> dict:
    documents = db.query(Document.priority_level).filter(Document.owner_id == owner_id).all()

    counts = {level: 0 for level in LEVEL_ORDER}
    unclassified = 0
    for (level,) in documents:
        if level in counts:
            counts[level] += 1
        else:
            unclassified += 1

    return {**counts, "unclassified": unclassified, "total": len(documents)}
