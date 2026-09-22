# Ollama providers

Configure providers under **AI Providers**. Typical local endpoint: `http://localhost:11434`; select a model such as `llama3.2` after it is installed in Ollama. The application sends requests through its backend—not from browser JavaScript.

Private LAN HTTP is allowed only when `CAREERFORGE_ALLOW_PRIVATE_HTTP=true`. Remote providers require HTTPS and show the exact payload for confirmation before it is sent. Provider secrets are encrypted at rest, omitted from API/UI responses, audit logs, and Markdown. AI output is always **AI Draft — Review Required**; it cannot approve a record automatically.
