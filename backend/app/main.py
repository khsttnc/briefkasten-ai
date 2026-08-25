import logging
from typing import Optional

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .auth import get_current_user
from .billing import process_stripe_webhook
from .config import DEFAULT_FRONTEND_ORIGIN, FRONTEND_ORIGIN_ENV, env_or_default
from .database import engine, get_db
from .models import Base, User
from .services import (
    analyze_document,
    analyze_document_by_id,
    analyze_document_ai_by_id,
    get_documents_summary,
    list_documents,
    save_document,
)

logger = logging.getLogger("briefkasten")

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Briefkasten AI",
    description="AI assistant for German documents",
    version="0.1.0"
)

# Scoped to the single real frontend origin (never "*"), since requests now
# carry Authorization headers. See config.py for the env var / default.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[env_or_default(FRONTEND_ORIGIN_ENV, DEFAULT_FRONTEND_ORIGIN)],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/health")
def health():
    # Unauthenticated and touches no DB/external service on purpose - this
    # is a liveness probe for the container/reverse proxy, not a readiness
    # check for the AI provider or database.
    return {"status": "ok"}


@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    document = save_document(file, db, owner_id=current_user.id)

    return {
        "id": document.id,
        "filename": file.filename,
        "status": "uploaded"
    }


@app.get("/analyze/id/{document_id}")
def analyze_document_by_id_route(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analyze_document_by_id(document_id, db, owner_id=current_user.id)


@app.post("/analyze/id/{document_id}/ai")
def analyze_document_ai_by_id_route(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analyze_document_ai_by_id(document_id, db, owner_id=current_user.id)


@app.get("/documents")
def list_documents_route(
    priority: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_documents(db, owner_id=current_user.id, priority=priority)


@app.get("/documents/summary")
def documents_summary_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_documents_summary(db, owner_id=current_user.id)


@app.get("/analyze/{filename}", deprecated=True)
def analyze_document_route(
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Deprecated in favor of /analyze/id/{document_id} - filename is not a
    # unique key, see services.analyze_document.
    return analyze_document(filename, db, owner_id=current_user.id)


@app.post("/webhooks/stripe")
async def stripe_webhook_route(request: Request, db: Session = Depends(get_db)):
    # Raw bytes, not a parsed Pydantic model - Stripe's signature is computed
    # over the exact request body, and re-serializing a parsed model would
    # not reproduce it byte-for-byte.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    return process_stripe_webhook(payload, sig_header, db)

