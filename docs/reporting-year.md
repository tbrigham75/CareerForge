# Reporting year and History

Settings → Reporting Year is an organization-wide setting stored in SQLite (and thus
included in backups). Default: calendar year, January 1–December 31, UTC. Choose an
IANA organization timezone explicitly; the browser/system timezone is not assumed.
The pinned tzdata dependency provides timezone rules on Windows.

Fiscal mode supports any starting month, always starting on day 1. Choose the starting
or ending year for labels (October 2025–September 2026 is FY 2025 or FY 2026).
Preview dates does not save. Save applies the setting across all sessions and records.

Accomplishments defaults to the current reporting year. Records with status completed
or legacy archived and a completion date are grouped by that date. All other statuses,
and records without a completion date, stay in the current workspace. All years includes
past/current/future dates. Dashboard recent work follows the current-year view; its total
is explicitly all years, including archived records but excluding Trash.

History lists completed records before the current reporting year's start. Select a year
or all previous years; search and existing date/project/tag/technology/sensitivity filters
still apply. Include archived is independent. Open any record normally to view/edit it.
Changing completion dates/status or reporting settings can change which view contains it.

Rollover is computed at each request using organization-local midnight. No scheduler,
physical move, archive operation, or deletion is required. An already open page reflects
the new year when refreshed. The application can be off at the boundary without missing
rollover. Date-only completion values are never converted between timezones.

Reports and exports keep their existing all-year scope; generated report snapshots are
unchanged. Archived records remain indefinitely and Trash still expires after 30 days.
For archive recovery across years use Accomplishments → All years → Include archived.

Migration 0007 adds only a settings table and does not modify accomplishment content.
This release supports month-based calendars, not 4-4-5 or 52/53-week retail calendars.
