# Resume Builder

Resume Builder lives under Share your progress. It uses the configured local/private-network Ollama-compatible provider; there is no external AI fallback. Upload DOCX, ODT, or a text-based PDF. Originals and approved versions remain separate, immutable files under the configured data directory's `resumes` folder.

## Accomplishments and suggestions

The workspace keeps its live accomplishment inventory visible before and after generation. Four counters distinguish ready sources, records needing review, valid AI recommendation cards, and the user's selected cards. A saved shortlist of one change does not hide other eligible work. A grouped suggestion can cite multiple sources; recommendation counts refer to cards, not distinct accomplishments.

- **Ready:** approved, completed or archived, report-included, non-deleted work dated between January 1 and today in the organization's timezone. This uses the calendar year, independent of the fiscal year. Missing metrics do not exclude qualitative work.
- **Needs review:** current-year or undated records that fail eligibility, including unfinished notes, missing approval, future dates, report exclusions, or explicit suppression. Notes are never promoted automatically. The list links to each record for review.
- **Already represented:** sources incorporated into an approved version whose recorded revision has not changed. Changed sources may be reconsidered. An AI opinion that wording already covers a source is separately labeled as an AI assessment in Ready.

Missing completion dates default to the original entry date. Editing a record later does not make old work current-year work. Migration 0009 backfills non-deleted records, preserving explicit dates and recording conflicts where the start date would exceed the default completion date.

Confirm the current role, insertion point and section boundaries, choose a local provider and a length goal, and optionally nominate accomplishments for extra consideration. A single identifiable current role is prefilled; ambiguous roles require a choice. Job targeting is optional and influences relevance only. Mark critical existing paragraphs Keep.

Generation evaluates supplied eligible sources and can return up to eight options per request. The prompt separates useful ideas from the recommended length-constrained subset; additional options can be alternatives. It does not force a minimum count or fabricate facts. Each Ready source offers **Suggest wording for this** once a draft exists, so omitted work can be explored individually. Grouped sources and explanations are visible on each card. Missing AI explanations are disclosed rather than invented.

## Refreshing a draft

The screen compares the live inventory to the last saved review, displaying counts of newly available, changed and no-longer-eligible sources. GET requests never call the model. Older drafts without timestamps are supported and labeled honestly.

**Refresh suggestions** re-evaluates current eligible work while keeping existing cards in order, edited wording, selection and suppression choices. Edits are saved before provider/configuration checks; a failed provider request returns an error notice while retaining the draft. New options are appended, labeled, and unselected. Exact repeats of original generated wording are not appended again after a user edits that wording. Individual requests only update the requested source's review snapshot; unrelated new work remains marked newly available.

Each card retains the source revision and evidence used to generate it. Refreshing the overall source list cannot silently validate old wording against changed facts. Outdated cards stay visible for reference, but must be deselected before approval; request and review a new option. Concurrent tabs use optimistic revision checks and cannot overwrite newer saved work.

## Selecting, previewing and saving

All newly generated options start unchecked. Additions, replacements, combinations and removals require explicit selection. Skipping is temporary; the separate suppression checkbox excludes sources from future suggestions. Suppression can be reset from advanced controls after finishing or discarding the draft.

Desktop shows suggestions and a sticky content preview side by side. Smaller screens offer Suggestions/Preview view buttons. Save draft and Save approved resume remain available below either view. Category and view buttons support keyboard activation, retain accessible pressed state, and use the shared theme tokens. Without JavaScript, categories and both review panels remain visible; server validation still enforces approval rules.

The preview highlights new/replaced/removed text and measures current-role word count against the persistent length goal. Excess length requires explicit permission. Selecting cards with overlapping source IDs or paragraph targets shows a conflict, pauses the preview and blocks approval; the server also rejects those combinations. Outdated source cards are blocked likewise. Draft saving remains available while resolving conflicts. Historical roles, protected paragraphs, and the uploaded original remain protected. Saved document text is checked against the deterministic preview before committing a version.

Version downloads, restoring an earlier approved version as a new working baseline, and suppression reset live under Version history and advanced controls. Restore never deletes later versions; finish or discard a proposal first.

## Limits

PDF text is reconstructed into Word paragraphs and requires manual layout review. Scanned/encrypted PDFs and complex Word tables/text boxes are unsupported. DOCX and ODT retain native output formats. Role/date parsing is heuristic, so confirm section boundaries carefully. Word counts and automated numeric/duplicate checks cannot guarantee page length, semantic accuracy, or perfect relevance. Review claims yourself.

Paginated preview requires local LibreOffice. It does not install software or invoke cloud conversion. The always-available content preview is not a page-layout renderer; installed fonts affect final pagination. Generation has bounded request/response sizes and no automatic batching for very large archives. Useful work remains visible even when the model returns fewer options than expected, and an individual request may still return no grounded improvement.

Full backups include the resumes folder. Database-only maintenance snapshots do not include document files. Resume files are not registered with accomplishment attachment cleanup and are not sent to Git Sync.

## Validation handoff for the workspace redesign

No new dependency or schema migration is needed for this redesign. Restart the existing web process to load updated Python routes. No application, model call, browser session, migration, or test suite was run during this phase. Regression cases are prepared in `tests/test_resume_sources.py` and `tests/test_resume_workspace.py`, alongside the existing document tests in `tests/test_resumes.py`.

Run the repository's `scripts/test.ps1` (tests use isolated data), or in PowerShell:

```powershell
$env:PYTHONPATH = 'backend'
.\.venv\Scripts\python.exe -m pytest tests/test_resumes.py tests/test_resume_sources.py tests/test_resume_workspace.py
```

Manual acceptance checks:

1. Open an older one-source draft with three eligible accomplishments: all three remain visible, with two newly available.
2. Edit and select the original card, refresh, and confirm its wording/selection remain while new cards start unchecked.
3. Request wording for an omitted source; verify the new option cites it and is not automatically inserted. Repeat without creating duplicate cards with identical generated wording.
4. Change or remove a source, then refresh. Its old card must remain flagged and cannot be approved. Raw notes remain in Needs review until explicitly completed/approved.
5. Simulate an unavailable provider and two open tabs. Confirm draft edits survive failure and stale revisions cannot overwrite a newer draft.
6. Select overlapping alternatives and exceed the length goal. Confirm clear feedback, draft saving, explicit growth permission, and server-side rejection of conflicts even without JavaScript.
7. Review each theme in light/dark mode, keyboard-only interaction, narrow mobile layout, both mobile views, provider validation inside collapsed controls, and empty inventory states.
8. Approve a nonconflicting selection, verify original bytes are unchanged and output matches preview, reopen to see represented sources, then restore an older approved version. Check DOCX/ODT separately and pagination if LibreOffice is available.
