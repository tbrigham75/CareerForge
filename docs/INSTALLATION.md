# Installation

Prerequisites: Windows PowerShell, Git for Windows, and Python 3.12 or 3.13 installed with the `py` launcher. Node.js is not required because the interface is server-rendered. Ollama is optional.

From the repository root:

```powershell
./scripts/bootstrap.ps1
./scripts/run-dev.ps1
```

Open `http://127.0.0.1:8000`, then create the first local administrator account. Bootstrap creates `.venv`, installs exact declared dependencies, creates `.env` only when absent, creates an encryption key without printing it, and applies migrations. It does not modify the reference `.odt` file.
