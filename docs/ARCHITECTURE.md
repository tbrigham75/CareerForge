# Architecture

CareerForge is a single-process, local FastAPI application using server-rendered Jinja pages. The browser talks only to `127.0.0.1`; backend services own SQLite, local files, `.docx` generation, Git subprocesses, and Ollama-compatible HTTP calls. No container, cloud database, or hosted backend is required.

`backend/app/models.py` defines relational records. SQLite lives under `%LOCALAPPDATA%\CareerForge\data`; Alembic records schema revision `0001_initial`. Writable data, reports, logs, attachments, exports, and encrypted configuration remain outside the checkout.

The provider adapter validates endpoint schemes and classifications before making an outbound call. It blocks known metadata hosts and dangerous address classes, disallows remote HTTP, disables redirects, limits response size, and keeps credentials backend-only.
