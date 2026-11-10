# Resume Builder

Resume Builder appears under Share your progress. Upload DOCX, ODT, or a text-based PDF. The original is saved unchanged under the configured data directory's resumes folder. PDF content is reconstructed into Word paragraphs and requires manual baseline/layout review. Scanned PDFs, encrypted files, and complex Word tables/text boxes are not supported by this initial importer.

Confirm the current employer/role and paragraph after which new bullets belong. Explicit year-to-year historical date ranges are protected. Ambiguous dates and employer assignments require careful user confirmation; the parser does not understand every international date convention.

Update Resume uses the configured local/private-network Ollama-compatible provider. Only approved, completed, report-included, non-deleted accomplishments completed between January 1 and today are considered. This is a calendar-year selection independent of fiscal settings. Sources previously accepted or rejected for that resume are excluded. No attachments are sent. No external AI fallback is used.

Review source evidence, edit suggestions, save a draft, discard, or approve selected additions. Unchecked suggestions are remembered as rejected when saving. Existing content is retained and each approved update creates a separate downloadable version. Previous versions remain available. Word and ODT retain their native output format; PDFs produce an editable Word baseline. Use Word/LibreOffice for final pagination and PDF export.

The current implementation uses an addition word budget, source identity, normalized text comparisons and AI duplicate instructions. These are not a guarantee of semantic factual verification or exact page length. User review remains essential. Changed sources previously incorporated are not automatically proposed again. Restore an earlier approved version as a new working baseline without deleting later versions. Reconsider previously rejected sources using the dedicated control. Finish or discard a pending proposal first.

## Installation and validation handoff

Install the updated requirements (pypdf was added), then run the normal startup script to apply migration 0008. The running server must be restarted to load these changes. No dependency installation, migration, restart, AI call, or tests were executed during implementation.

Prepared tests: tests/test_resumes.py. Run these and the existing regression suite in an isolated data directory. Manually verify upload/download for all three formats, originals byte-for-byte unchanged, current role placement, historical section protection, saved drafts, concurrent edits, repeat updates, rejected bullets, disabled/remote/unreachable providers, malformed model replies, placeholders, unsupported numbers, missing dates, excluded records, calendar rollover in the organization timezone, and fiscal/calendar differences.

Full backups include the resumes folder. Database-only maintenance snapshots do not include files. Confirm file/version availability after a full restore. Resume files are not registered in the accomplishment attachment cleanup system and are not sent to Git Sync.

## Reviewed editing upgrade

The review workflow now supports linked additions, replacements, combinations and removals. Changes to existing text start unchecked and require explicit acceptance. Confirm current-role boundaries before generating, and mark critical paragraphs Keep. Source eligibility still uses the click-year calendar dates. Optional job targeting is blank by default and supplies relevance context only.

Length goals apply to the resulting section; a persistent baseline prevents repeated updates from resetting the allowance. Excess length requires explicit approval. Unchecked changes are skipped temporarily; the separate suppression checkbox prevents future source suggestions and can be reset. Current-year sources with changed revisions may be reconsidered. Existing versions made before revision tracking may need an additional human review during their first upgraded update.

The live content preview shares paragraph-edit semantics with document saving. Saved output text is checked against the approved result. Local paginated preview uses LibreOffice if installed; it does not install software or invoke cloud conversion. Fonts and rendering engines can affect pagination. No renderer or application was executed as part of this implementation.

Additional prepared checks cover protected/historical sections, overlapping edits, atomic replacement/combination and preview/output parity. End-to-end UI, real provider behavior, ODT rendering, failed renderer cleanup, restoration provenance, and complex date boundaries still require execution in your test environment.
