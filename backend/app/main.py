import logging

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .database import engine, get_db
from .models import Base
from .services import analyze_document, analyze_document_by_id, analyze_document_ai_by_id, save_document

logger = logging.getLogger("briefkasten")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Briefkasten AI",
    description="AI assistant for German documents",
    version="0.1.0"
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    # HTTPException (used throughout services.py) is handled by FastAPI's
    # own, more specific handler and never reaches this one. This only
    # catches genuinely unexpected errors, so the client gets a safe,
    # generic message instead of a raw stack trace, while the real
    # exception is still logged server-side for diagnosis.
    logger.error(
        "Unhandled error while processing %s %s", request.method, request.url.path, exc_info=exc
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again later."},
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

