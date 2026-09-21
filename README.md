# CareerForge

> Turn completed work into documented impact.

CareerForge will be a local-first, self-hosted archive for professional accomplishments. It will preserve raw notes and evidence, optionally use an Ollama-compatible writing assistant, generate `.docx` reports, and export only approved Markdown to Git repositories.

## Current status

The project is in the **planning milestone**. No application code, database, native standalone runtime, or integrations have been implemented yet. The approved architecture and phased delivery plan are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

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

- React + TypeScript + Vite frontend
- FastAPI + SQLAlchemy + Alembic backend
- SQLite with migrations as the authoritative local database
- `python-docx` for deterministic server-side Word output
- Native standalone installation for Windows and Linux; no Docker dependency

## Next step

Review the decisions in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#decisions-needed-before-implementation). Once approved, implementation starts with the repository scaffold, local authentication, migrations, and accomplishment capture.
