from fastapi import Depends, FastAPI, File, UploadFile
from sqlalchemy.orm import Session

from .database import engine, get_db
from .models import Base
from .services import analyze_document, analyze_document_by_id, analyze_document_ai_by_id, save_document

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Briefkasten AI",
    description="AI assistant for German documents",
    version="0.1.0"
)


@app.get("/")
def home():
    return {
        "message": "Welcome to Briefkasten AI"
    }


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    document = save_document(file, db)

    return {
        "id": document.id,
        "filename": file.filename,
        "status": "uploaded"
    }


@app.get("/analyze/id/{document_id}")
def analyze_document_by_id_route(
    document_id: int,
    db: Session = Depends(get_db),
):
    return analyze_document_by_id(document_id, db)


@app.post("/analyze/id/{document_id}/ai")
def analyze_document_ai_by_id_route(
    document_id: int,
    db: Session = Depends(get_db),
):
    return analyze_document_ai_by_id(document_id, db)


@app.get("/analyze/{filename}")
def analyze_document_route(
    filename: str,
    db: Session = Depends(get_db),
):
    return analyze_document(filename, db)

