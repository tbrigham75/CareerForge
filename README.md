# CareerForge

> Turn completed work into documented impact.

CareerForge is a private, local-first Windows application for capturing accomplishments,
preserving evidence, drafting factual Action-Metric-Impact entries, generating Word reports,
and exporting approved Markdown safely. It runs with native Windows processes only—no Docker,
containers, cloud database, or mandatory online service.

## Status

Version 0.1.0 is an in-progress local application. See [Installation](docs/INSTALLATION.md),
[Operations](docs/OPERATIONS.md), and [Testing](docs/TESTING.md).

## Quick start

1. Install Python 3.12 or 3.13 and Git for Windows.
2. In PowerShell, run `./scripts/bootstrap.ps1`.
3. Run `./scripts/run-dev.ps1` and visit `http://127.0.0.1:8000`.
4. Create the local administrator account on the first visit.

Application data is stored under `%LOCALAPPDATA%\\CareerForge` by default, never in the
repository. The reference `Tom's Brag Sheet.odt` remains local and is intentionally ignored.

## Core safety principles

- AI assistance is optional and drafts are always marked **AI Draft — Review Required**.
- The original raw note is retained; AI never silently approves or overwrites a record.
- Provider secrets are encrypted at rest and are never returned to browsers.
- Markdown exports exclude `do_not_sync` and non-export-eligible records.
- Git commit and push actions require an explicit confirmation in the application.

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Configuration](docs/CONFIGURATION.md)
- [Security](docs/SECURITY.md)
- [Ollama providers](docs/OLLAMA.md)
- [Reports](docs/REPORTS.md)
- [Git export](docs/GIT_EXPORT.md)
- [Backup and restore](docs/BACKUP_RESTORE.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

Screenshot placeholders will be stored in `docs/images/` when a stable UI release is available.
