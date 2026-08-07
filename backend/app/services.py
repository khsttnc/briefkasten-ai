import os
import shutil
from fastapi import UploadFile, HTTPException
from sqlalchemy.orm import Session
import fitz

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


def analyze_document(filename: str, db: Session) -> dict:
    document = (
        db.query(Document)
        .filter(Document.filename == filename)
        .order_by(Document.id.desc())
        .first()
    )

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.status == "analyzed" and document.text is not None and document.character_count is not None:
        return {
            "filename": filename,
            "characters": document.character_count,
            "text": document.text[:1000],
        }

    if not os.path.exists(document.filepath):
        raise HTTPException(status_code=404, detail="Uploaded file not found on disk")

    doc = fitz.open(document.filepath)
    text = ""
    for page in doc:
        text += page.get_text()

    document.text = text
    document.character_count = len(text)
    document.status = "analyzed"

    db.add(document)
    db.commit()
    db.refresh(document)

    return {
        "filename": filename,
        "characters": document.character_count,
        "text": document.text[:1000],
    }
