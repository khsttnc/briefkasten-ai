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

DATABASE_PATH = BASE_DIR / "briefkasten.db"
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATABASE_PATH.as_posix()}")

UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", str(BASE_DIR / "uploads"))

def _default_tesseract_cmd() -> str:
    # Windows installers don't add tesseract.exe to PATH, so keep the known
    # default install location there. On Linux/macOS, tesseract is typically
    # installed via a package manager and already on PATH.
    if platform.system() == "Windows":
        return r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    return "tesseract"


TESSERACT_CMD = os.getenv("TESSERACT_CMD", _default_tesseract_cmd())

AI_PROVIDER_ENV = "AI_PROVIDER"
DEFAULT_AI_PROVIDER = "claude"

ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
ANTHROPIC_MODEL_ENV = "ANTHROPIC_MODEL"
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"

OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"
OLLAMA_MODEL_ENV = "OLLAMA_MODEL"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
