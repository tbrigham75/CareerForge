# User Acceptance Test

Run these on a fresh clone and record the outcome.

1. **Fresh install:** run `./scripts/bootstrap.ps1`, then `./scripts/run-dev.ps1`; expected: `http://127.0.0.1:8000` opens first-run administrator setup.
2. **Raw note:** enter “I updated a PowerShell script used for stale Active Directory account cleanup.” and choose **Save Raw Note**; expected: it appears in Dashboard and Accomplishments with no AI connection.
3. **Manual entry:** enter Action, Metric, and Impact and save completed; expected: it is searchable and revision history is visible.
4. **AI:** configure local Ollama, draft a note; expected: output reads **AI Draft — Review Required**, unsupported facts are placeholders, and raw note remains available.
5. **AI failure:** use an invalid endpoint; expected: a clear error with no data loss and raw note still available.
6. **Search:** search tag, technology, and text; expected: applicable records appear.
7. **Report:** select records and generate a report; expected: a Word `.docx` opens with Action, Metric, and Impact headings.
8. **Markdown:** preview export; expected: a manifest excludes non-approved, confidential, and `do_not_sync` records.
9. **Backup:** create a backup; expected: a ZIP exists. Test restore using a separate data directory.
10. **Security:** verify `.env` is ignored, credentials do not display/log/export, and Git actions need confirmation.

## Sign-off

| Field | Value |
| --- | --- |
| Date / tester | |
| App version / commit | |
| Windows / Python / browser | |
| Ollama provider/model | |
| Passed / failed scenarios | |
| Known issues | |
| Approval decision | |
