import logging
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from .account_deletion import delete_account, get_deletion_preview
from .auth import get_current_user
from .billing import process_stripe_webhook
from .config import (
    AI_ANALYZE_RATE_LIMIT,
    DEFAULT_FRONTEND_ORIGIN,
    DEFAULT_RATE_LIMIT,
    FRONTEND_ORIGIN_ENV,
    UPLOAD_RATE_LIMIT,
    env_or_default,
)
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


def _rate_limit_key(request: Request) -> str:
    # Keyed by authenticated user id when available (set by auth.py's
    # get_current_user via request.state.user_id) so a per-account limit
    # is enforced regardless of shared/rotating IPs. Falls back to the
    # client IP for requests the default (middleware-level) limit checks
    # before FastAPI has resolved the route's auth dependency - e.g. the
    # global default_limits below, which run before get_current_user - and
    # for genuinely unauthenticated routes like /webhooks/stripe.
    user_id = getattr(request.state, "user_id", None)
    return f"user:{user_id}" if user_id is not None else get_remote_address(request)


# In-memory storage (no Redis) is deliberate: this deploys as a single
# backend container (see docker-compose.yml), not a horizontally-scaled
# fleet, so there is exactly one process whose memory needs to agree.
limiter = Limiter(key_func=_rate_limit_key, default_limits=[DEFAULT_RATE_LIMIT])
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


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
@limiter.limit(UPLOAD_RATE_LIMIT)
async def upload_document(
    request: Request,
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
@limiter.limit(AI_ANALYZE_RATE_LIMIT)
def analyze_document_ai_by_id_route(
    request: Request,
    document_id: int,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return analyze_document_ai_by_id(document_id, db, owner_id=current_user.id, force=force)


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


class AccountDeletionRequest(BaseModel):
    # Server-side check backing the frontend's "type your email to confirm"
    # step (see CLAUDE.md: destructive actions must be confirmed) - not
    # just a UI nicety, this is verified against the authenticated user's
    # own email below.
    confirmation_email: str


@app.get("/account/deletion-preview")
def account_deletion_preview_route(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return get_deletion_preview(current_user, db)


@app.delete("/account")
def delete_account_route(
    body: AccountDeletionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    expected_email = (current_user.email or "").strip().lower()
    submitted_email = (body.confirmation_email or "").strip().lower()
    if not expected_email or submitted_email != expected_email:
        raise HTTPException(status_code=400, detail="E-posta doğrulaması başarısız.")

    delete_account(current_user, db)
    return {"status": "deleted"}


@app.post("/webhooks/stripe")
async def stripe_webhook_route(request: Request, db: Session = Depends(get_db)):
    # Raw bytes, not a parsed Pydantic model - Stripe's signature is computed
    # over the exact request body, and re-serializing a parsed model would
    # not reproduce it byte-for-byte.
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    return process_stripe_webhook(payload, sig_header, db)

