import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
import fitz
from PIL import Image
import pytesseract

from .config import TESSERACT_CMD, UPLOAD_FOLDER

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD

from .ai_service import AIService
from .models import Document, DocumentAIAnalysis
from .providers.provider_factory import get_ai_provider
from .document_processing import DocumentProcessingOrchestrator

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

UPLOAD_ROOT = Path(UPLOAD_FOLDER).resolve()

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif"}
MAX_UPLOAD_SIZE_BYTES = int(os.getenv("MAX_UPLOAD_SIZE_MB", "50")) * 1024 * 1024
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


def save_document(file: UploadFile, db: Session) -> Document:
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

    document = Document(
        filename=safe_display_name,
        filepath=str(file_path),
        status="uploaded",
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document


def extract_text_with_ocr(filepath: str) -> str:
    doc = fitz.open(filepath)
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

    return "\n".join(pages_text)


def _ensure_document_analyzed(document: Document, db: Session) -> dict:
    if document.status == "analyzed" and document.text is not None and document.character_count is not None:
        return {
            "filename": document.filename,
            "characters": document.character_count,
            "text": document.text[:1000],
        }

    if not os.path.exists(document.filepath):
        raise HTTPException(status_code=404, detail="Uploaded file not found on disk")

    doc = fitz.open(document.filepath)
    text = ""
    for page in doc:
        text += page.get_text()

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


def analyze_document(filename: str, db: Session) -> dict:
    document = (
        db.query(Document)
        .filter(Document.filename == filename)
        .order_by(Document.id.desc())
        .first()
    )

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return _ensure_document_analyzed(document, db)


def analyze_document_by_id(document_id: int, db: Session) -> dict:
    document = db.query(Document).filter(Document.id == document_id).first()

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return _ensure_document_analyzed(document, db)


def analyze_document_ai_by_id(document_id: int, db: Session) -> dict:
    document = db.query(Document).filter(Document.id == document_id).first()

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

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
            completed_at=datetime.utcnow(),
        )
        db.add(analysis_record)
        db.commit()
        db.refresh(analysis_record)

        raise HTTPException(status_code=503, detail=str(exc))

    orchestrator = DocumentProcessingOrchestrator(provider)
    analysis_result = orchestrator.run(document.text or "")

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
        completed_at=datetime.utcnow(),
    )

    db.add(analysis_record)
    db.commit()
    db.refresh(analysis_record)

    response = {
        "analysis_id": analysis_record.id,
        "document_id": analysis_record.document_id,
        "provider": analysis_record.provider,
        "model": analysis_record.model,
        "status": analysis_record.status,
        "document_type": analysis_record.document_type,
        "language": analysis_record.language,
        "summary": analysis_record.summary,
        "turkish_explanation": analysis_record.turkish_explanation,
        "important_dates": analysis_result.important_dates or [],
        "extracted_entities": analysis_result.extracted_entities or [],
        "error_message": analysis_record.error_message,
    }

    if analysis_result.error_message:
        raise HTTPException(status_code=502, detail=analysis_result.error_message)

    return response
