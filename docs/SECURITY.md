# Security

- Passwords use Argon2 hashes; browser sessions are signed, same-site cookies with expiry.
- State-changing form operations require a CSRF token. Login attempts have a local in-memory rate limit.
- SQLite ORM calls are parameterized. Git uses argument arrays with `shell=False`.
- AI endpoint validation blocks malformed URLs, embedded credentials, metadata hosts, link-local/multicast/reserved IPs, redirects, and oversized responses.
- `do_not_sync`, confidential, and unapproved records are excluded from Markdown export.

This is a single-user local application, not a multi-user security boundary. Bind it to `127.0.0.1` unless you have assessed an alternate deployment.
