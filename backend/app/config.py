from pathlib import Path
import os
import platform

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/

try:
    from dotenv import load_dotenv

    # override=True: backend/.env is the project's authoritative local config
    # (see CLAUDE.md). Without it, python-dotenv's default (do not override
    # already-set process env vars) means a stale AI_PROVIDER/ANTHROPIC_API_KEY
    # left over from an earlier shell session silently wins over .env, causing
    # the app to call Claude even when .env says AI_PROVIDER=ollama.
    load_dotenv(BASE_DIR / ".env", override=True)
except ImportError:
    pass

def env_or_default(name: str, default: str) -> str:
    """os.getenv(name, default), but empty-string-safe.

    Plain os.getenv only falls back to `default` when `name` is entirely
    absent from the environment - a variable that IS present but set to an
    empty value (e.g. a "NAME=" line copied verbatim from .env.example
    without filling it in) makes it return "" instead. That silently broke
    TESSERACT_CMD, NVIDIA_BASE_URL, and NVIDIA_MODEL in production. Treat
    "" the same as unset everywhere a real default exists.
    """
    value = os.getenv(name)
    return value if value else default


DATABASE_PATH = BASE_DIR / "briefkasten.db"
DATABASE_URL = env_or_default("DATABASE_URL", f"sqlite:///{DATABASE_PATH.as_posix()}")

UPLOAD_FOLDER = env_or_default("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))

def _default_tesseract_cmd() -> str:
    # Windows installers don't add tesseract.exe to PATH, so keep the known
    # default install location there. On Linux/macOS, tesseract is typically
    # installed via a package manager and already on PATH.
    if platform.system() == "Windows":
        return r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    return "tesseract"


TESSERACT_CMD = env_or_default("TESSERACT_CMD", _default_tesseract_cmd())

AI_PROVIDER_ENV = "AI_PROVIDER"
DEFAULT_AI_PROVIDER = "claude"

ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_MODEL_ENV = "ANTHROPIC_MODEL"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"

OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
OLLAMA_MODEL_ENV = "OLLAMA_MODEL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

NVIDIA_API_KEY_ENV = "NVIDIA_API_KEY"
NVIDIA_MODEL_ENV = "NVIDIA_MODEL"
NVIDIA_BASE_URL_ENV = "NVIDIA_BASE_URL"
DEFAULT_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_NVIDIA_MODEL = "nvidia/nemotron-3-nano-30b-a3b"

# Supabase Auth issues user JWTs signed with the project's asymmetric
# (ES256/P-256) signing key. auth.py verifies them against the public key
# published at this project's JWKS endpoint
# (<SUPABASE_URL>/auth/v1/.well-known/jwks.json) - never a shared secret.
# No default: a missing URL must fail loudly (auth.py returns 503), never
# silently accept an unverifiable token.
SUPABASE_URL_ENV = "SUPABASE_URL"

# CORS: the single real frontend origin allowed to call this API with
# credentials/Authorization headers - never "*" once auth is involved.
# Defaults to the Vite dev server; production must override via env.
FRONTEND_ORIGIN_ENV = "FRONTEND_ORIGIN"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:5173"

# Stripe webhook signing secret (Stripe Dashboard -> Webhooks -> the
# endpoint's "Signing secret"). No default: a missing secret must fail
# loudly (billing.py returns 503), never silently accept an unverified
# webhook payload.
STRIPE_WEBHOOK_SECRET_ENV = "STRIPE_WEBHOOK_SECRET"

# --- Rate limiting (slowapi) ---
# Security review finding: /upload and the AI-analyze endpoint had no
# request-rate limit at all - a single account could call either
# unboundedly, which is both a trivial CPU-exhaustion DoS (OCR is
# CPU-heavy) and a direct cost-abuse vector against the paid AI provider
# API. Values are deliberately generous for a real user's normal workflow
# (uploading/analyzing a handful of documents in a sitting) while still
# bounding worst-case abuse. slowapi rate-string format: "<count>/<period>".
DEFAULT_RATE_LIMIT = env_or_default("DEFAULT_RATE_LIMIT", "60/minute")
UPLOAD_RATE_LIMIT = env_or_default("UPLOAD_RATE_LIMIT", "10/minute")
AI_ANALYZE_RATE_LIMIT = env_or_default("AI_ANALYZE_RATE_LIMIT", "10/minute")

# --- Document processing limits ---
# Security review finding: no cap existed on a PDF's page count or on a
# page's rendered pixel dimensions before OCR - a small-file-size but
# pathological PDF (thousands of pages, or a page/MediaBox declaring an
# enormous size) could tie up a worker for a long time or exhaust memory
# in fitz.Page.get_pixmap(), independent of MAX_UPLOAD_SIZE_MB (which only
# bounds bytes on disk, not page count or declared page dimensions).
#
# MAX_DOCUMENT_PAGES: document_processing.py's own truncation-ceiling
# comment already established "a ~200-page contract or insurance policy"
# as the realistic worst case seen in practice; 300 keeps a margin above
# that without allowing an effectively unbounded page count.
MAX_DOCUMENT_PAGES = int(env_or_default("MAX_DOCUMENT_PAGES", "300"))
# MAX_PAGE_DIMENSION_POINTS: fitz reports page size in points (1/72 inch)
# via page.rect: real documents (A4, Letter, Legal, even an A0 poster) are
# all well under 3000pt on their longest side. 5000pt (~69in / ~1.75m)
# comfortably covers any real scanned page while still bounding the
# pixmap buffer get_pixmap() would allocate at default (1:1) resolution.
MAX_PAGE_DIMENSION_POINTS = int(env_or_default("MAX_PAGE_DIMENSION_POINTS", "5000"))
