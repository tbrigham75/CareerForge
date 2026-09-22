# Testing

Run all automated tests with `./scripts/test.ps1`. Run linting, type checks, and tests with `./scripts/check.ps1`.

Tests cover first-run setup, login failure/success/logout, raw-note capture/search, encryption, outbound endpoint policy, revisions/archive, `.docx` output, and Markdown export. AI network calls are not made in the automated suite; provider behavior should be tested against a controlled local Ollama instance.
