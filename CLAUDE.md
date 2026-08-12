# Briefkasten AI - Claude Code Rules

## Project
Briefkasten AI is a German-document processing application.
Backend: FastAPI + SQLAlchemy + SQLite.
Frontend: React + TypeScript + Vite.
AI providers: Claude and Ollama.

## Safety Rules
- Never delete or overwrite existing user data.
- Never migrate, reset, recreate, or clear the SQLite database unless explicitly instructed.
- Preserve backend/briefkasten.db and its existing data.
- Never modify or delete files in codebase-memory-mcp/.
- Never run git commit or git push unless explicitly requested.
- Before making significant code changes, inspect the relevant existing code first.
- Do not invent project structure or behavior; verify it from the repository.
- Prefer small, focused changes.
- Preserve existing API behavior unless the task explicitly requires changing it.

## Database and Files
- The canonical database is backend/briefkasten.db.
- The canonical upload directory is backend/uploads/.
- Database and upload paths must remain independent of the current working directory.
- Do not move existing database records or uploaded files unless explicitly requested.

## Configuration
- Central configuration lives in backend/app/config.py.
- Environment variables should be handled through the centralized configuration.
- Secrets must never be hardcoded or committed.
- backend/.env should not be committed.
- Keep environment configuration compatible with the existing provider architecture.

## Development Workflow
For implementation tasks:
1. Inspect relevant files.
2. Explain the intended change briefly when confirmation is required.
3. Make the smallest appropriate change.
4. Run relevant validation/tests.
5. Show git diff/status.
6. Never commit or push unless explicitly requested.

## Testing
- Do not weaken or remove existing tests merely to make them pass.
- If tests cannot run because of environment/dependency problems, report the exact cause.
- Distinguish between code failures and environment/setup failures.

## Communication
- Be concise.
- Do not repeat the entire project analysis unnecessarily.
- Before destructive or irreversible actions, stop and ask for explicit confirmation.
