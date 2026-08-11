import json
import os
import shutil
from datetime import datetime
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
import fitz
from PIL import Image
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from .ai_service import AIService
from .models import Document, DocumentAIAnalysis
from .providers.provider_factory import get_ai_provider
from .document_processing import DocumentProcessingOrchestrator

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def save_document(file: UploadFile, db: Session) -> Document:
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    document = Document(
        filename=file.filename,
        filepath=file_path,
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
