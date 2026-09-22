# Security Review Checklist

- [ ] `.env`, data directory, reference ODT, reports, attachments, and keys are ignored by Git.
- [ ] First-run password has at least 12 characters and Argon2 hashing is active.
- [ ] Cookies use secure settings appropriate to the selected local transport.
- [ ] CSRF is exercised on all state-changing HTML forms.
- [ ] Provider secrets never render, log, or export.
- [ ] Remote provider payload confirmation is tested.
- [ ] Metadata/link-local and remote HTTP endpoints are rejected.
- [ ] `do_not_sync`, confidential, and unapproved exports are blocked.
- [ ] Backup restore is tested with non-production data.
- [ ] Git commit/push previews and explicit confirmations are reviewed before enabling live sync.
