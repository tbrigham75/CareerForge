# Interface and theme system

The existing FastAPI/Jinja architecture and form contracts are retained. No production dependencies were added.

## Shared components

- `backend/app/templates/base.html`: grouped sidebar navigation, active route, mobile disclosure, skip link, theme preferences and shared feedback.
- `backend/app/static/app.css`: palette, typography, spacing, border and shadow tokens; responsive forms, cards, tables, controls and semantic feedback.
- `backend/app/static/theme.js`: synchronous pre-paint preference application, safe storage fallback and live operating-system appearance changes.
- `backend/app/static/app.js`: preference controls, mobile navigation, accessible table scrolling, document titles and validation/loading feedback. Submitter names and values remain intact.
- Dashboard, capture, login/setup and report-order templates have targeted layout and labeling improvements. All other pages inherit the shared components.

## Preferences

Open **Theme & appearance** at the top of any page. Choose Slate, Ocean, Emerald, Violet, Amber or Rose, then select Light, Dark or System independently. Preferences are local to the browser, stored under `careerforge-style`. System follows the OS immediately. Each palette changes backgrounds, panels, navigation, borders and accents. Semantic success/error/warning colors remain consistent across palettes.

The blocking theme script precedes the stylesheet and body to apply stored appearance before painting. Invalid or unavailable storage falls back to Slate/System; unavailable persistence is disclosed when changing preferences.

## Verification (2026-10-07)

- Ruff and mypy: passed.
- Existing pytest suite: 12 passed; existing framework deprecation warnings remain.
- Isolated headless Microsoft Edge audit: 14 authenticated page variants at 1440, 768, 390 and 320 CSS pixels (56 checks), with no page-wide horizontal overflow and accessible input names.
- All 12 light/dark palettes: persisted across reloads; dashboard screenshots captured; capture, projects, providers and reports loaded in each combination.
- Measured text token pairs meet 4.5:1 contrast; input boundary token pairs meet 3:1. Includes accent-on-tinted-surface and semantic feedback pairs.
- Setup/login, empty dashboard, dated capture, project creation, report selection/download, date validation, reduced motion, live OS appearance, Escape dismissal, mobile menu and keyboard skip link: passed. No browser JavaScript errors.
- Screenshot inspection: Slate light, Amber light, Rose dark and mobile capture.

This is not a formal WCAG certification or a complete assistive-technology/cross-browser audit. Native confirmation dialogs remain browser/OS controlled. Actual remote AI and Git integrations were not exercised by this visual audit.

## Local path selection

Exports provides Browse folders for the Git repository root and its export subdirectory; Imports provides Browse files filtered to ODT documents. The shared themed dialog lists drives and folders, supports manual navigation, pagination, cancellation and keyboard focus restoration. Subdirectory choices are relative to and bounded by the selected repository. Manual entry remains available for new export folder names. Selection never submits the parent form or modifies the selected source. The authenticated, CSRF-protected `/files/browse` endpoint lists paths on the computer running CareerForge; network/device paths are excluded. Existing import/export confirmations remain required.

Verification added: three backend tests covering authentication, CSRF, ODT filtering, unchanged source contents, repository validation, boundary enforcement and invalid locations. The browser audit now also exercises all three pickers and mobile cancellation/focus restoration.

## Reproduce checks

Install optional `playwright==1.63.0` into the development virtual environment; the browser check uses installed Microsoft Edge. Run `.venv/Scripts/python.exe scripts/ui_check.py`. It migrates a disposable database under ignored `temp/ui-review/`, starts its own loopback server and stops it afterward. Screenshots, a JSON results file and server logs remain there for inspection. User data and source documents are untouched.

Run `.venv/Scripts/python.exe -m ruff check backend tests scripts/ui_check.py` and `.venv/Scripts/python.exe -m mypy backend`. For pytest, set `PYTHONPATH=backend`; if Windows denies the default Temp/cache directories, use `-p no:cacheprovider --basetemp=temp/pytest-ui-redesign` with a directory dedicated to test output.
