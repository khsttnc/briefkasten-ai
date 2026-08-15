# Briefkasten AI

Briefkasten AI is a document processing assistant for German official and
corporate documents. Users upload a PDF (or scanned image), the backend
extracts the text (with OCR fallback for scanned/image-only pages), and an
AI provider produces a structured analysis: document type, language,
a German-to-Turkish explanation, and extracted dates/entities.

## Features

- German document upload (PDF, PNG, JPG/JPEG, TIFF)
- PDF text extraction (PyMuPDF)
- OCR fallback for scanned/image-only documents (Tesseract)
- AI-powered document analysis
- German → Turkish explanation of document content
- Document classification (type, language)
- Entity and important-date extraction
- Pluggable AI provider: Claude (Anthropic) or Ollama (local models)
- Local-first document processing (SQLite + local file storage)

## Architecture

**Frontend**
React + TypeScript + Vite

**Backend**
FastAPI + SQLAlchemy + SQLite

**Document processing**
PyMuPDF (text extraction) + Tesseract (OCR fallback)

**AI**
Claude (Anthropic API) or Ollama (local), selected via configuration

## Requirements

- Python 3.11+ (developed/tested with 3.14)
- Node.js 20+ and npm (developed/tested with Node 26)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) installed
  locally, only required for scanned/image-based documents that have no
  extractable text layer
- One of:
  - An Anthropic API key (for the Claude provider), or
  - A running [Ollama](https://ollama.com/) instance with a pulled model
    (for the Ollama provider)

## Installation

### Backend

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Frontend

```bash
cd frontend
npm install
```

### Environment configuration

```bash
cd backend
cp .env.example .env
# then edit backend/.env with your real values
```

`backend/.env` is gitignored and must never be committed.

## Environment Variables

See [`backend/.env.example`](backend/.env.example) for the full list with
inline descriptions. Summary:

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AI_PROVIDER` | No | `claude` | `claude` or `ollama` |
| `ANTHROPIC_API_KEY` | Only if `AI_PROVIDER=claude` | — | Claude API key |
| `ANTHROPIC_MODEL` | No | `claude-opus-5` | Claude model to use |
| `OLLAMA_MODEL` | Only if `AI_PROVIDER=ollama` | — | Ollama model name |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama server URL |
| `TESSERACT_CMD` | No | OS-appropriate default | Path to the Tesseract executable |
| `DATABASE_URL` | No | Local SQLite file at `backend/briefkasten.db` | SQLAlchemy database URL |
| `UPLOAD_FOLDER` | No | `backend/uploads/` | Directory for uploaded files |
| `MAX_UPLOAD_SIZE_MB` | No | `50` | Maximum accepted upload size |

## Running locally

### Backend

```bash
cd backend
.venv\Scripts\activate   # or: source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

The API is served at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm run dev
```

The dev server runs at `http://localhost:5173` and proxies `/api/*`
requests to the backend on `http://localhost:8000` (see
`frontend/vite.config.ts`).

## Testing

### Backend (run from the repository root)

```bash
python -m unittest discover -s backend/app -p "test_*.py" -t .
```

### Frontend

```bash
cd frontend
npm test -- --run
```

### TypeScript check

```bash
cd frontend
npx tsc --noEmit
```

### Build

```bash
cd frontend
npm run build
```

## Project Structure

```
backend/
  app/
    main.py                 # FastAPI app and routes
    config.py                # Centralized environment/configuration
    database.py               # SQLAlchemy engine/session setup
    models.py                  # Document, DocumentAIAnalysis models
    services.py                 # Upload, text extraction, OCR, AI orchestration
    document_processing.py       # Orchestrates provider calls
    ai_service.py                  # AIAnalysisResult, provider protocol
    processors.py                   # Task-specific prompt processors
    providers/                       # Claude and Ollama provider implementations
  requirements.txt
  briefkasten.db              # local SQLite database (gitignored)
  uploads/                     # uploaded files, stored under generated names (gitignored)

frontend/
  src/
    App.tsx                   # Upload/analysis UI
    api.ts                     # Backend API client
    components/landing/         # Marketing landing page sections
```

## Security Notes

- User-uploaded files are stored on disk under a generated (UUID-based)
  filename with a validated extension; the client-supplied filename is
  never used as a filesystem path, and is only kept as sanitized display
  metadata.
- Uploads are restricted to `backend/uploads/`, validated for a known file
  extension, rejected if empty, and capped at `MAX_UPLOAD_SIZE_MB`.
- Secrets (API keys) are read from environment variables only and are never
  hardcoded or logged. `backend/.env` is gitignored.
- The local SQLite database (`backend/briefkasten.db`) and `backend/uploads/`
  may contain real uploaded documents; do not commit them.

## Production Notes

This project is currently structured for local/single-user development.
Before any production deployment, the following should be addressed:

- Serve the API behind HTTPS (e.g. via a reverse proxy such as nginx or
  Caddy).
- Replace the local SQLite file with a production-grade database if
  concurrent/multi-user access is expected.
- Use persistent, backed-up storage for `UPLOAD_FOLDER` instead of local
  disk (e.g. a mounted volume or object storage), especially in
  containerized/ephemeral deployments.
- Manage secrets (API keys) via a proper secrets manager or platform
  environment configuration, not `.env` files, in production.
- Run the backend behind a reverse proxy that enforces request size limits
  and TLS termination.
- Add structured logging and monitoring/alerting; none is currently
  configured.
- Review and configure CORS explicitly if the frontend and backend are
  served from different origins in production (the current dev setup relies
  on the Vite dev proxy, and no CORS middleware is configured in the
  FastAPI app).
- For a public launch targeting German users/customers, legally required
  pages (e.g. Impressum, Datenschutzerklärung) will be needed. These are
  not included here and require legal review before launch — not addressed
  by this codebase.
