# Capture, taxonomy, browsing, and report workflows

Saving an accomplishment registers systems/services, technologies, tags, and categories
in the same transaction. Labels are comma-separated, trimmed, and matched using Unicode
case folding. Removing a label from an accomplishment leaves the reusable entry intact.
Direct Taxonomy additions never change accomplishments. Sensitivity remains a controlled
privacy setting, not a taxonomy group. Capture and edit forms suggest existing labels.

On I Did This, a project is required when saving a completed accomplishment; raw notes
may omit it. Start and completion dates initialize to the browser's local calendar day
and remain editable. Failed-save values and user-edited dates are not reset. After AI
assistance, a steady highlighted reminder asks the user to review the project and dates;
an optional acknowledgment clears the highlighting without changing those values.
Projects can be created in a separate tab and refreshed without discarding the draft.

The Backups screen retains `/operations` and `/operations/backup` for compatibility.

Appearance, AI Providers, Backups, and Audit Log are grouped in the **Settings** dialog
opened from the sidebar footer. Management pages include a Settings breadcrumb; their
existing URLs still work. Opening and closing Settings does not navigate away from an
unsaved form. Before sign-in, Settings exposes only browser-local appearance preferences.

## Filesystem boundaries

For a direct localhost connection on an interactive Windows desktop, Exports and Imports
now open the standard **Windows Common Item Dialog** (folder selection for repositories
and export folders; file selection for ODT documents). It runs on the CareerForge PC,
requires authentication and CSRF validation, accepts only one active dialog, and times out
after three minutes. Cancel leaves the form unchanged. Every returned path is checked
again using the existing local-drive, file-type, and repository-containment restrictions.
Remote/proxied connections and non-Windows servers retain the labeled server-browser
fallback; they cannot open a window on someone else's desktop. Advanced path entry remains.

- Repository folders, export subfolders, and ODT import sources are on the **server**
  running CareerForge. The authenticated picker browses that filesystem with breadcrumbs,
  drive/location choices, folder navigation, and explicit selection. Cancel never changes
  the form. Existing OS access limits, network/device-path rejection, and repository
  containment checks remain in effect. Hidden folders can be shown explicitly.
- Document attachments use the browser's native file input and upload bytes, not a local
  path that is assumed to exist on the server.
- Reports retain managed server copies. The editable output filename applies to downloads.
  **Browse save location** uses the browser's native save API where available (typically
  desktop Edge/Chrome in a secure context, including localhost). It cannot expose a local
  absolute path to the server. Cancel preserves the selected handle. Other browsers use
  normal downloads and their own “ask where to save” setting. Handles are session-only and
  are never stored in report templates. Selecting an existing destination can replace it
  when the user generates the report; the native save dialog provides the overwrite prompt.

## Reports

New reports start with an editable date-based title/filename, Word output, and every
eligible accomplishment selected. Archived, deleted, or report-excluded records are not
eligible. Search and completion dates narrow scope. Selections remain attached to each
record when filtering; templates never replace them. Empty reports are rejected.

Named templates persist title, notes, report type, and output filename, using the existing
single-administrator ownership model. They do not store files, file handles, or record IDs.
Selecting a template applies only saved fields, confirms before overwriting edited values,
and allows further changes. Updating/deleting a template does not alter generated reports.

Migration `0005_starter_reports` installs eight editable starter templates: Executive
Summary, Monthly Update, Quarterly Review, Annual Self-Assessment, Promotion Evidence,
Project Closeout, Security & Compliance, and Technical Operations. They supply useful
titles, introductory notes, filenames, report types, and one of three document layouts:
Detailed, Impact first, or Compact. Layout is editable, saved in templates and reports,
and retained when a generated report is reordered. Templates never preselect evidence or
assert accomplishments that the user has not recorded. Installation happens once, skips
existing names, and does not overwrite customizations or recreate deleted starters on reload.

Native file and folder dialogs were instantiated, opened, and canceled in Windows smoke
tests. Headless browser tests mock their selection responses and verify form routing and
cancel preservation; backend tests validate the selected paths and access restrictions.

## Migration 0004_workflow_settings

Adds `system_services`, normalized unique label identities to the existing taxonomy tables,
and JSON settings to `report_templates`. Existing template notes become reusable settings.
Legacy duplicate taxonomy rows are retained with distinct legacy identities (not deleted)
and shown once in the UI; new saves reuse the canonical identity. Existing accomplishment
labels are registered when those accomplishments are next saved, not silently rewritten.

Automated browser coverage mocks the operating-system save dialog but tests real report
generation and transfer to its writable interface. Server folder browsing, cancellation,
template CRUD, selections, responsive layouts, and themes are tested directly.
