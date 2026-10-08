# Exports and Git Sync

Exports downloads selected accomplishments directly through the browser in Word (.docx),
OpenDocument (.odt), or Excel (.xlsx). No repository, AI provider, or external service is
required. Word and ODT use the reference brag sheet's Action / Metric / Impact structure,
with record titles, dates, projects, status, and sensitivity. The original reference file
is never used as an output destination or changed.

Filter by current/all/specific reporting year, project, and search. Completed records
are shown by default; optionally include unfinished and archived work. Select records,
choose a title/format, and confirm sensitivity review. Raw and supporting notes are
opt-in. Uploaded attachments are not embedded. Missing fields say Not provided; no AI
rewriting occurs. Records are revalidated against the scope at download time. Trash is
always excluded. Downloads are audited and not retained as server-side files.

Excel uses native dates, filters, frozen headings and literal text cells (never formulas
or automatic hyperlinks from user content). Long text remains in cells; expand row heights
when needed. Exports are local copies and are not automatically erased by later deletion.

Git Sync retains the existing approved/eligible/sensitivity-restricted Markdown pipeline.
Preview, write, commit, and push remain distinct confirmation-gated operations. New routes
use /git-sync; legacy /exports/... Git endpoints remain compatibility aliases. Reports
continues to provide its existing template and saved-report workflow.

Verification includes document parsing, content checks, Excel formula-injection checks,
and browser downloads for all three formats. The local QA renderer cannot render Word/ODT
pages because bundled LibreOffice is unavailable; printed layout still needs a manual
check in Word or LibreOffice. Application-page responsive checks are separate and pass.
