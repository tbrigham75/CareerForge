# CareerForge

> Turn completed work into documented impact.

CareerForge will be a local-first, self-hosted archive for professional accomplishments. It will preserve raw notes and evidence, optionally use an Ollama-compatible writing assistant, generate `.docx` reports, and export only approved Markdown to Git repositories.

## Current status

The current native FastAPI + SQLite build provides one-time local administrator setup, authenticated sessions that survive page refresh, CSRF protection, Home capture and Accomplishments, Goals with review-required AI suggestions, active-session Chat, and AI/Ollama provider settings with connection testing. The interface defaults to Dark and includes Slate, Forest, Ocean, and Sunset themes; the theme and Settings controls are compact icons in the top-right corner. Reports, Markdown/Git export, projects/evidence, search, source import, and detailed editing remain planned. The architecture and phased delivery plan are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Guiding rules

- The local database is authoritative; Git and GitHub are optional exports.
- Raw notes and user-approved wording are retained separately from AI drafts.
- AI is a drafting tool, never a factual source. Missing facts must be visible placeholders and follow-up questions.
- The browser communicates only with the CareerForge backend, never an AI provider directly.
- Exports, commits, and pushes are previewed and explicitly confirmed in the future application.
- The application remains useful offline and with AI or Git unavailable.

## Reference source

`Tom's Brag Sheet.odt` remains an unmodified local reference document. It is not an application data store and will not be included in exported content. A later, idempotent importer will record source path, file name, hash, import time, and outcome.

## Proposed stack

- Server-served HTML, CSS, and JavaScript interface (bundled into the executable)
- FastAPI + SQLAlchemy backend
- SQLite as the authoritative local database (the current release creates its required tables at startup; versioned migrations are a planned hardening item)
- `python-docx` for deterministic server-side Word output
- Native standalone installation for Windows and Linux; no Docker dependency

## Run in development

1. Create a virtual environment: `py -m venv .venv`
2. Install packages from the project metadata: `.\.venv\Scripts\python.exe -m pip install --index-url https://pypi.org/simple -e ".[dev]"`
3. Start the local app: `.\.venv\Scripts\python.exe -m uvicorn careerforge.main:app --host 127.0.0.1 --port 8787`
4. Open `http://127.0.0.1:8787/` and complete the one-time local setup.

## Downloadable standalone build

Release builds are native executables. A Windows build bundles Python and all application dependencies, so a downloader runs `CareerForge.exe` directly and does not install Python, Node, Docker, a database server, or packages. Neither running the executable nor creating it needs administrator rights. By default it stores data per user in `%LOCALAPPDATA%\CareerForge`; `CAREERFORGE_DATA_DIR` can choose another writable directory. Launch the executable and keep it running while using the browser tab—do not open `index.html` directly. The entry page is not cached and bundled client assets are versioned, so an upgrade replaces the browser client cleanly. Close the executable before replacing it with an updated build. Build it from the source checkout with `scripts\build-windows.ps1`; Linux distributions must be built on Linux.

The launcher tracks each CareerForge browser tab. When the last tab closes, the local process exits promptly; an eight-second stale-tab fallback also cleans up after a browser crash. Keeping any CareerForge tab open keeps the local application running.

## Verification

Run `.\.venv\Scripts\python.exe -m pytest -q`. The suite verifies one-time local setup, the 10-character password minimum, no password disclosure, authenticated raw-note CRUD with revisions and soft deletion, CSRF enforcement, the served UI, and the launcher heartbeat endpoint. `node --check careerforge\static\app.js` validates the browser client syntax.

## Next step

Next: add schema migrations, project and evidence records, search, and the safe source-document import workflow.
