# Operations

Run development mode with `./scripts/run-dev.ps1`; use `./scripts/run-prod.ps1` for a local non-reloading process. Stop it with `Ctrl+C`. Logs and operational data are under `%LOCALAPPDATA%\CareerForge` unless overridden.

Run `./scripts/check.ps1` before updating dependencies. Update pinned dependencies in a clean virtual environment, review all changes, then re-run checks. Apply migrations with `py -3.13 -m app.migrate` after setting `PYTHONPATH=backend` (the run scripts do this automatically).

To read the supplied source document without changing it, use `./scripts/import-reference.ps1`. The importer records the absolute source path, filename, hash, status, and time; a repeat with the same completed file is recorded as `skipped_duplicate` and creates no duplicate accomplishments. If extraction is unsuitable for the document, use manual raw-note capture instead.
