# Testing

Run all automated tests with `./scripts/test.ps1`. Run linting, type checks, and tests with `./scripts/check.ps1`.

Tests cover first-run setup, login failure/success/logout, raw-note capture/search, projects, evidence, local attachment storage/download, encryption, outbound endpoint policy, revisions/archive, `.docx` output, Markdown export, confirmation-gated Git mutations, and backup ZIP path validation. AI network calls are not made in the automated suite; provider behavior should be tested against a controlled local Ollama instance.
