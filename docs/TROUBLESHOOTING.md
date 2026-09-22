# Troubleshooting

**`py` is not found:** install Python 3.12/3.13 from python.org and enable the launcher.

**Bootstrap cannot install packages:** check proxy/network access to PyPI, then rerun it; package versions are declared in the repository.

**App cannot decrypt provider credentials:** restore the matching `CAREERFORGE_ENCRYPTION_KEY` from `.env` or re-enter provider credentials.

**Ollama connection fails:** verify Ollama is running, endpoint/model are correct, and the endpoint passes local/remote policy. Save raw notes without AI while troubleshooting.

**Port 8000 is busy:** stop the existing local server, or set a different Uvicorn port manually and browse to that port.
