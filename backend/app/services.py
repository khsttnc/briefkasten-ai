import os
import shutil
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
import fitz
from PIL import Image
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

from .models import Document

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
