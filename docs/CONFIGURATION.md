# Configuration

Copy `.env.example` to `.env` (bootstrap does this safely). `CAREERFORGE_DATA_DIR` can override the default `%LOCALAPPDATA%\CareerForge` location. `CAREERFORGE_ENCRYPTION_KEY` is a Fernet key used for provider credentials; protect it and back it up with the database. `CAREERFORGE_ALLOW_PRIVATE_HTTP` only permits HTTP for local/LAN endpoints. Keep `CAREERFORGE_COOKIE_SECURE=false` for plain local HTTP and use `true` behind trusted local HTTPS.

Never commit `.env`, encryption keys, databases, reports, or attachments.
