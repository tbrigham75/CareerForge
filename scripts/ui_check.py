"""Isolated browser acceptance checks. Requires optional Playwright + installed Edge.

Run: .venv/Scripts/python.exe scripts/ui_check.py
Artifacts and disposable database go under ignored temp/, never the user's data.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet
from playwright.sync_api import Error as BrowserError
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "temp" / "ui-review"
ARTIFACTS.mkdir(parents=True, exist_ok=True)
data_dir = tempfile.mkdtemp(prefix="database-", dir=ARTIFACTS)
env = dict(
    os.environ,
    PYTHONPATH=str(ROOT / "backend"),
    CAREERFORGE_DATA_DIR=data_dir,
    CAREERFORGE_ENCRYPTION_KEY=Fernet.generate_key().decode(),
)
subprocess.run([sys.executable, "-m", "app.migrate"], cwd=ROOT, env=env, check=True)
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
base = f"http://127.0.0.1:{port}"
log = (ARTIFACTS / "server.log").open("w")
server = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
    cwd=ROOT,
    env=env,
    stdout=log,
    stderr=log,
)
results = {"themes": [], "pages": [], "interactions": [], "errors": []}


def no_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), page.url


try:
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True, args=["--no-proxy-server"])
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.on("pageerror", lambda error: results["errors"].append(str(error)))
        for startup_attempt in range(3):
            try:
                page.goto(base + "/setup")
                break
            except BrowserError as exc:
                if startup_attempt == 2 or "ERR_CONNECTION_RESET" not in str(exc):
                    raise
                page.wait_for_timeout(500)
        page.get_by_label("Username", exact=True).fill("ui-review")
        page.get_by_label("Password (12+ characters)", exact=True).fill("isolated review password")
        page.get_by_label("Confirm password", exact=True).fill("isolated review password")
        page.get_by_role("button", name="Create administrator").click()
        for login_theme in ["slate", "ocean", "emerald", "violet", "amber", "rose"]:
            for login_mode in ["light", "dark"]:
                page.evaluate(
                    "args => window.careerforgeTheme.set(...args)", [login_theme, login_mode]
                )
                page.get_by_label("Username", exact=True).fill("ui-review")
                page.get_by_label("Password", exact=True).fill("isolated review password")
                colors = page.locator('input[name="username"]').evaluate("""el => {
                  const s = getComputedStyle(el);
                  const lum = c => c.match(/[\\d.]+/g).slice(0,3).map(Number).map(v => {v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
                  const a=lum(s.color), b=lum(s.backgroundColor); return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
                }""")
                assert colors >= 4.5, (login_theme, login_mode, colors)
                page.screenshot(
                    path=str(ARTIFACTS / f"login-{login_theme}-{login_mode}.png"), full_page=True
                )
        page.get_by_label("Username", exact=True).fill("ui-review")
        page.get_by_label("Password", exact=True).fill("isolated review password")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/dashboard")
        for label, route in [
            ("AI Providers", "/providers"),
            ("Backups", "/operations"),
            ("Audit Log", "/audit"),
        ]:
            expect(
                page.locator("#workspace-nav").get_by_role("link", name=label, exact=True)
            ).to_have_count(0)
            page.get_by_role("button", name="Settings", exact=True).click()
            settings_dialog = page.get_by_role("dialog", name="Settings", exact=True)
            expect(
                settings_dialog.get_by_role("heading", name="Appearance", exact=True)
            ).to_be_visible()
            settings_dialog.get_by_role("link", name=label, exact=True).click()
            page.wait_for_url("**" + route)
            page.get_by_role("navigation", name="Breadcrumb", exact=True).get_by_role(
                "button", name="Settings", exact=True
            ).click()
            expect(settings_dialog.get_by_role("link", name=label, exact=True)).to_have_attribute(
                "aria-current", "page"
            )
            page.keyboard.press("Escape")
            expect(
                page.get_by_role("navigation", name="Breadcrumb", exact=True).get_by_role(
                    "button", name="Settings", exact=True
                )
            ).to_be_focused()
            page.goto(base + "/dashboard")
        page.goto(base + "/capture")
        page.get_by_label("What did you do?").fill(
            "Unsaved note stays here while adjusting settings."
        )
        page.get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("button", name="Done", exact=True).click()
        expect(page.get_by_label("What did you do?")).to_have_value(
            "Unsaved note stays here while adjusting settings."
        )
        page.goto(base + "/dashboard")
        # Exercise the server fallback without opening OS windows in headless tests.
        page.route(
            "**/files/picker-capabilities", lambda route: route.fulfill(json={"native": False})
        )
        # Browse only selects paths; it must never submit either parent form.
        fixture_repo = Path(data_dir) / "browse-repository"
        fixture_repo.mkdir()
        subprocess.run(["git", "init", str(fixture_repo)], check=True, capture_output=True)
        (fixture_repo / "exports").mkdir()
        fixture_source = fixture_repo / "Example.ODT"
        fixture_source.write_bytes(b"read-only picker fixture")
        page.goto(base + "/exports")
        page.locator('[data-browse="subdirectory"]').click()
        expect(page.locator("dialog [data-status]")).to_contain_text("Choose or enter a repository")
        page.keyboard.press("Escape")
        page.locator('[data-browse="repository"]').locator("..").get_by_role(
            "button", name="Edit path (advanced)", exact=True
        ).click()
        page.get_by_label("Repository path", exact=True).fill(str(fixture_repo))
        page.locator('[data-browse="repository"]').click()
        expect(page.locator("dialog [data-select]")).to_be_enabled()
        page.locator("dialog [data-select]").click()
        expect(page.locator(".file-browser")).not_to_be_visible()
        expect(page.get_by_label("Repository path", exact=True)).to_have_value(
            str(fixture_repo.resolve())
        )
        page.locator('[data-browse="subdirectory"]').click()
        page.get_by_role("button", name="Open folder exports", exact=True).click()
        expect(page.locator("#browser-location")).to_have_value(str(fixture_repo / "exports"))
        page.locator("dialog [data-select]").click()
        expect(page.get_by_label("Export subdirectory", exact=True)).to_have_value("exports")
        assert page.url == base + "/exports"
        page.goto(base + "/imports")
        page.get_by_role("button", name="Edit path (advanced)", exact=True).click()
        page.get_by_label("Local ODT source path").fill(str(fixture_repo))
        page.get_by_role("button", name="Browse files", exact=True).click()
        expect(page.locator("dialog [data-select]")).not_to_be_visible()
        page.get_by_role("button", name="Select file Example.ODT", exact=True).click()
        page.get_by_role("button", name="Use selected file", exact=True).click()
        expect(page.get_by_label("Local ODT source path")).to_have_value(str(fixture_source))
        assert page.url == base + "/imports"
        page.get_by_role("button", name="Browse files", exact=True).click()
        expect(page.locator("dialog [data-status]")).to_contain_text("items shown")
        page.set_viewport_size({"width": 390, "height": 844})
        no_overflow(page)
        page.screenshot(path=str(ARTIFACTS / "browse-mobile.png"), full_page=True)
        page.keyboard.press("Escape")
        expect(page.get_by_role("button", name="Browse files", exact=True)).to_be_focused()
        expect(page.get_by_label("Local ODT source path")).to_have_value(str(fixture_source))
        assert fixture_source.read_bytes() == b"read-only picker fixture"
        page.unroute("**/files/picker-capabilities")
        page.route(
            "**/files/picker-capabilities", lambda route: route.fulfill(json={"native": True})
        )

        def native_selection(route):
            from urllib.parse import parse_qs

            submitted = parse_qs(route.request.post_data)
            kind = submitted["kind"][0]
            route.fulfill(
                json={
                    "selected": {
                        "repository": str(fixture_repo.resolve()),
                        "subdirectory": "exports",
                        "odt": str(fixture_source),
                    }[kind]
                }
            )

        page.route("**/files/pick-native", native_selection)
        page.goto(base + "/exports")
        page.locator('[data-browse="repository"]').click()
        expect(page.get_by_label("Repository path", exact=True)).to_have_value(
            str(fixture_repo.resolve())
        )
        expect(page.locator(".file-browser")).not_to_be_visible()
        page.locator('[data-browse="subdirectory"]').click()
        expect(page.get_by_label("Export subdirectory", exact=True)).to_have_value("exports")
        page.goto(base + "/imports")
        page.get_by_role("button", name="Browse files", exact=True).click()
        expect(page.get_by_label("Local ODT source path")).to_have_value(str(fixture_source))
        expect(page.locator(".file-browser")).not_to_be_visible()
        page.unroute("**/files/pick-native")
        page.route("**/files/pick-native", lambda route: route.fulfill(json={"canceled": True}))
        page.get_by_role("button", name="Browse files", exact=True).click()
        expect(page.locator("[data-native-status]")).to_contain_text("Canceled")
        expect(page.get_by_label("Local ODT source path")).to_have_value(str(fixture_source))
        page.set_viewport_size({"width": 1440, "height": 1000})
        results["interactions"].append(
            "Repository picker, relative export folder, ODT filtering/selection, cancellation and focus restoration; no automatic submissions"
        )
        page.goto(base + "/dashboard")
        assert page.locator(".empty-state").is_visible()
        page.goto(base + "/capture")
        expect(
            page.get_by_role("link", name="Set up AI Provider (opens a new tab)")
        ).to_be_visible()
        page.goto(base + "/providers")
        page.get_by_label("Display name", exact=True).fill("UI test provider")
        page.get_by_label("Base URL", exact=True).fill("https://example.com")
        page.get_by_label("Default model", exact=True).fill("test-model")
        page.get_by_role("button", name="Save provider", exact=True).click()
        page.goto(base + "/capture")
        page.get_by_label("What did you do?").fill("Patched four Linux servers.")
        local_today = page.evaluate(
            "() => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }"
        )
        expect(page.get_by_label("Start date", exact=True)).to_have_value(local_today)
        expect(page.get_by_label("Completion date", exact=True)).to_have_value(local_today)
        page.get_by_label("Start date", exact=True).fill("2026-10-01")
        page.get_by_label("Completion date", exact=True).fill("2026-10-05")
        page.get_by_label("Title", exact=True).fill("My own title")
        page.route(
            "**/capture/assist",
            lambda route: route.fulfill(
                json={
                    "draft": {
                        "title": "Patched servers",
                        "action": "Patched four Linux servers.",
                        "metric": "Four servers",
                        "impact": "[Confirm outcome]",
                        "supporting_narrative": "",
                        "suggested_systems": ["Linux"],
                        "suggested_technologies": [],
                        "suggested_tags": ["patching"],
                        "suggested_categories": [],
                        "field_questions": {
                            "impact": "What was the verified outcome?",
                            "metric": "How many settings did you review?",
                        },
                        "questions": [],
                    }
                }
            ),
        )
        page.get_by_role("button", name="Help me fill this out", exact=True).click()
        expect(page.get_by_label("Action", exact=True)).to_have_value("Patched four Linux servers.")
        expect(page.locator("#capture-context-reminder")).to_be_visible()
        expect(page.locator(".capture-review-field.needs-review")).to_have_count(3)
        expect(page.get_by_label("Start date", exact=True)).to_have_value("2026-10-01")
        expect(page.get_by_label("Completion date", exact=True)).to_have_value("2026-10-05")
        expect(page.get_by_label("Metric", exact=True)).to_have_value("Four servers")
        expect(page.get_by_label("Impact", exact=True)).to_have_value("[Confirm outcome]")
        expect(page.get_by_label("Title", exact=True)).to_have_value("My own title")
        expect(page.get_by_label("What did you do?")).to_have_value("Patched four Linux servers.")
        page.get_by_role("button", name="Replace Title with suggestion", exact=True).click()
        expect(page.get_by_label("Title", exact=True)).to_have_value("Patched servers")
        page.unroute("**/capture/assist")
        page.get_by_label("What was the verified outcome?", exact=True).fill(
            "All services restarted successfully."
        )
        page.get_by_label("Action", exact=True).fill("My manually refined action")
        page.get_by_label("Supporting evidence / notes", exact=True).fill(
            "Keep this evidence unchanged."
        )
        page.get_by_label("How many settings did you review?", exact=True).fill(
            "Reviewed 24 CIS settings and identified 3 exceptions."
        )

        def rewrite_response(route):
            from urllib.parse import parse_qs

            submitted = parse_qs(route.request.post_data)
            field = submitted["target_field"][0]
            assert submitted["raw_note"][0] == "Patched four Linux servers."
            expected = {
                "metric": (
                    "Reviewed 24 CIS settings and identified 3 exceptions.",
                    "Assessed 24 CIS settings, identifying 3 exceptions.",
                ),
                "impact": (
                    "All services restarted successfully.",
                    "Verified successful restart of all services.",
                ),
            }
            answer, wording = expected[field]
            assert submitted["target_answer"][0] == answer
            route.fulfill(json={"field": field, "suggestion": wording})

        page.route("**/capture/assist", rewrite_response)
        page.get_by_role("button", name="Update Metric from my answer", exact=True).click()
        expect(page.get_by_label("Metric", exact=True)).to_have_value(
            "Assessed 24 CIS settings, identifying 3 exceptions."
        )
        expect(page.get_by_label("Impact", exact=True)).to_have_value("[Confirm outcome]")
        page.get_by_role("button", name="Update Impact from my answer", exact=True).click()
        expect(page.get_by_label("Impact", exact=True)).to_have_value(
            "Verified successful restart of all services."
        )
        expect(page.get_by_label("Supporting evidence / notes", exact=True)).to_have_value(
            "Keep this evidence unchanged."
        )
        page.unroute("**/capture/assist")
        page.route(
            "**/capture/assist",
            lambda route: route.fulfill(status=502, json={"error": "Simulated provider outage"}),
        )
        page.get_by_role("button", name="Update Metric from my answer", exact=True).click()
        expect(page.locator("#assist-status")).to_have_text("Simulated provider outage")
        expect(page.get_by_label("Metric", exact=True)).to_have_value(
            "Assessed 24 CIS settings, identifying 3 exceptions."
        )
        page.get_by_role("button", name="Help me fill this out", exact=True).click()
        expect(page.locator("#assist-status")).to_have_text("Simulated provider outage")
        expect(page.get_by_label("What was the verified outcome?", exact=True)).to_have_value(
            "All services restarted successfully."
        )
        page.unroute("**/capture/assist")

        def refine_response(route):
            from urllib.parse import parse_qs

            submitted = parse_qs(route.request.post_data)
            assert "All services restarted successfully." in submitted["follow_up_answers"][0]
            assert "Field: impact" in submitted["follow_up_answers"][0]
            assert submitted["raw_note"][0] == "Patched four Linux servers."
            route.fulfill(
                json={
                    "draft": {
                        "title": "Patched servers",
                        "action": "Suggested new action",
                        "metric": "[Missing information]",
                        "impact": "[Missing information]",
                        "supporting_narrative": "Reviewed 24 CIS settings and identified 3 exceptions. All services restarted successfully.",
                        "questions": [],
                    }
                }
            )

        page.route("**/capture/assist", refine_response)
        page.get_by_role("button", name="Help me fill this out", exact=True).click()
        expect(page.get_by_label("Impact", exact=True)).to_have_value(
            "Verified successful restart of all services."
        )
        expect(page.get_by_label("Action", exact=True)).to_have_value("My manually refined action")
        expect(page.get_by_label("Metric", exact=True)).to_have_value(
            "Assessed 24 CIS settings, identifying 3 exceptions."
        )
        expect(page.get_by_label("Supporting evidence / notes", exact=True)).to_have_value(
            "Keep this evidence unchanged."
        )
        expect(page.get_by_label("What did you do?")).to_have_value("Patched four Linux servers.")
        page.unroute("**/capture/assist")
        results["interactions"].append(
            "AI setup guidance and simulated autofill: title preservation, explicit replacement, Action/Metric/Impact and unchanged raw note"
        )
        page.goto(base + "/capture")
        page.get_by_label("What did you do?").fill(
            "Automated weekly service checks, saving two hours per week."
        )
        page.get_by_label("Title", exact=True).fill("Made weekly service checks repeatable")
        page.get_by_label("Start date", exact=True).fill("2026-10-01")
        page.get_by_label("Completion date", exact=True).fill("2026-10-07")
        page.get_by_label("Browse computer for a document", exact=True).set_input_files(
            {"name": "assessment.txt", "mimeType": "text/plain", "buffer": b"Reviewed 24 settings."}
        )
        expect(page.locator("#supporting-document-status")).to_contain_text("assessment.txt")
        page.get_by_role("button", name="Clear file selection", exact=True).click()
        expect(page.locator("#supporting-document-status")).to_have_text("No document selected.")
        page.get_by_label("Browse computer for a document", exact=True).set_input_files(
            {"name": "assessment.txt", "mimeType": "text/plain", "buffer": b"Reviewed 24 settings."}
        )
        page.get_by_role("button", name="Save Completed Accomplishment").click()
        expect(page.get_by_label("Project", exact=True)).to_have_attribute("aria-invalid", "true")
        assert page.url == base + "/capture"
        project_page = context.new_page()
        project_page.goto(base + "/projects")
        project_page.get_by_label("Project name").fill("Service reliability")
        project_page.get_by_label("Description", exact=True).fill(
            "Make routine work more dependable."
        )
        project_page.get_by_role("button", name="Create project").click()
        expect(
            project_page.get_by_role("cell", name="Service reliability", exact=True)
        ).to_be_visible()
        project_page.close()
        page.get_by_role("button", name="Refresh projects", exact=True).click()
        expect(page.locator("#capture-project-status")).to_contain_text("Projects refreshed")
        page.get_by_label("Project", exact=True).select_option(label="Service reliability")
        page.get_by_role("button", name="Project and dates look correct", exact=True).click()
        expect(page.locator(".capture-review-field.needs-review")).to_have_count(0)
        expect(page.get_by_label("Start date", exact=True)).to_have_value("2026-10-01")
        page.get_by_role("button", name="Save Completed Accomplishment", exact=True).click()
        page.wait_for_url("**/accomplishments/*")
        record_url = page.url
        with page.expect_download() as evidence_download:
            page.get_by_role("link", name="assessment.txt", exact=True).click()
        assert evidence_download.value.suggested_filename == "assessment.txt"
        assert page.get_by_role(
            "heading", name="Made weekly service checks repeatable"
        ).is_visible()
        results["interactions"].append(
            "Setup, login, empty dashboard, dated accomplishment creation"
        )
        page.goto(base + "/reports")
        expect(page.locator('input[name="record_ids"]').first).to_be_checked()
        for starter in [
            "Executive Summary",
            "Monthly Update",
            "Quarterly Review",
            "Annual Self-Assessment",
            "Promotion Evidence",
            "Project Closeout",
            "Security & Compliance",
            "Technical Operations",
        ]:
            expect(page.locator("#report-template option").filter(has_text=starter)).to_have_count(
                1
            )
        page.locator("#report-template").select_option(label="Executive Summary")
        expect(page.get_by_label("Report layout", exact=True)).to_have_value("impact_first")
        page.locator("#report-template").select_option("")
        expect(page.locator("#report-selection-count")).to_contain_text("1 selected of 1")
        page.locator('input[name="record_ids"]').first.uncheck()
        page.get_by_label("Report title", exact=True).fill("Template title")
        page.get_by_label("Report notes", exact=True).fill("Notes for leadership")
        page.get_by_label("Template name", exact=True).fill("Monthly review")
        page.get_by_role("button", name="Save settings as new template", exact=True).click()
        expect(page.locator("#template-status")).to_contain_text("Template saved")
        template_id = page.locator("#report-template").input_value()
        page.get_by_label("Report title", exact=True).fill("My unsaved edit")
        page.locator("#report-template").select_option("")
        page.once("dialog", lambda dialog: dialog.dismiss())
        page.locator("#report-template").select_option(template_id)
        expect(page.get_by_label("Report title", exact=True)).to_have_value("My unsaved edit")
        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#report-template").select_option(template_id)
        expect(page.get_by_label("Report title", exact=True)).to_have_value("Template title")
        expect(page.locator('input[name="record_ids"]').first).not_to_be_checked()
        page.get_by_label("Report notes", exact=True).fill("Updated leadership notes")
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Update selected template", exact=True).click()
        expect(page.locator("#template-status")).to_contain_text("Template saved")
        page.reload()
        page.locator("#report-template").select_option(template_id)
        expect(page.get_by_label("Report notes", exact=True)).to_have_value(
            "Updated leadership notes"
        )
        page.get_by_role("button", name="Deselect all", exact=True).click()
        page.get_by_label("Search accomplishments", exact=True).fill("no matching records")
        expect(page.locator("#report-selection-count")).to_contain_text("0 selected of 0")
        page.get_by_label("Search accomplishments", exact=True).fill("")
        expect(page.locator("#report-selection-count")).to_contain_text("0 selected of 1")
        page.get_by_role("button", name="Generate .docx report", exact=True).click()
        expect(page.locator("#report-validation")).to_contain_text("Select at least one")
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete selected template", exact=True).click()
        expect(page.locator("#template-status")).to_contain_text("Template deleted")
        expect(page.get_by_label("Report notes", exact=True)).to_have_value(
            "Updated leadership notes"
        )
        expect(page.locator('input[name="record_ids"]').first).not_to_be_checked()
        page.get_by_role("button", name="Select all", exact=True).click()
        # Native dialog is mocked; report generation and byte transfer are real.
        page.evaluate(
            """window.showSaveFilePicker = async () => ({name: 'chosen-report.docx', createWritable: async () => ({write: async blob => window.savedReportBytes = blob.size, close: async () => {}, abort: async () => {}})})"""
        )
        page.get_by_role("button", name="Browse save location", exact=True).click()
        expect(page.locator("#report-destination-status")).to_contain_text("chosen-report.docx")
        page.evaluate(
            "() => { window.showSaveFilePicker = async () => { throw new DOMException('Canceled', 'AbortError'); }; }"
        )
        page.get_by_role("button", name="Browse save location", exact=True).click()
        expect(page.locator("#report-destination-status")).to_contain_text("chosen-report.docx")
        page.get_by_role("button", name="Generate .docx report", exact=True).click()
        expect(page.locator("#report-destination-status")).to_contain_text(
            "Saved chosen-report.docx"
        )
        assert page.evaluate("window.savedReportBytes") > 1000
        page.get_by_role("button", name="Use normal download location", exact=True).click()
        page.get_by_label("Report title").fill("October progress")
        page.locator('input[name="record_ids"]').first.check()
        with page.expect_download() as download:
            page.get_by_role("button", name="Generate .docx report").click()
        assert download.value.suggested_filename.endswith(".docx")
        page.goto(base + "/reports")
        page.get_by_role("link", name="October progress", exact=True).click()
        report_url = page.url
        assert page.get_by_role("link", name="Download .docx").is_visible()
        results["interactions"].append(
            "Project creation and report generation with checkbox selection"
        )
        routes = [
            "/dashboard",
            "/capture",
            "/accomplishments",
            "/projects",
            "/taxonomy",
            "/reports",
            "/exports",
            "/imports",
            "/operations",
            "/providers",
            "/audit",
            record_url,
            record_url + "/edit",
            report_url,
        ]
        for width in [1440, 768, 390, 320]:
            page.set_viewport_size({"width": width, "height": 1000})
            for route in routes:
                response = page.goto(route if route.startswith("http") else base + route)
                assert response.status == 200, (route, response.status)
                no_overflow(page)
                assert page.locator("main h1").count() == 1
                assert page.locator('input:not([type="hidden"]),textarea,select').evaluate_all(
                    "els => els.every(e => e.labels?.length || e.getAttribute('aria-label'))"
                ), route
                results["pages"].append({"route": route.replace(base, ""), "width": width})
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(base + "/dashboard")
        for theme in ["slate", "ocean", "emerald", "violet", "amber", "rose"]:
            for mode in ["light", "dark"]:
                page.get_by_role("button", name="Settings", exact=True).click()
                page.get_by_label("Color theme").select_option(theme)
                page.get_by_role("combobox", name="Appearance", exact=True).select_option(mode)
                page.reload()
                assert page.locator("html").get_attribute("data-theme") == theme
                assert page.locator("html").get_attribute("data-mode") == mode
                # Resolve actual CSS colors and measure WCAG luminance ratios.
                ratios = page.evaluate("""() => {
                  const probe = document.createElement('span'); document.body.append(probe);
                  const color = token => { probe.style.color = `var(--${token})`; return getComputedStyle(probe).color.match(/[\\d.]+/g).slice(0,3).map(Number); };
                  const lum = rgb => rgb.map(v => {v/=255; return v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4;}).reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
                  const pairs = [['ink','panel'],['muted','panel'],['muted','canvas'],['muted','sidebar'],['accent','canvas'],['accent','accent-soft'],['on-accent','accent'],['danger','danger-bg'],['success','success-bg'],['warning','warning-bg'],['field-border','panel']];
                  const result = pairs.map(([a,b]) => {const x=lum(color(a)),y=lum(color(b)); return {pair:a+'/'+b,ratio:(Math.max(x,y)+.05)/(Math.min(x,y)+.05)};}); probe.remove(); return result;
                }""")
                for ratio in ratios:
                    assert ratio["ratio"] >= (
                        3 if ratio["pair"].startswith("field-border") else 4.5
                    ), (theme, mode, ratio)
                page.screenshot(path=str(ARTIFACTS / f"{theme}-{mode}.png"), full_page=True)
                results["themes"].append({"theme": theme, "mode": mode, "contrast": ratios})
                for route in ["/capture", "/projects", "/providers", "/reports"]:
                    assert page.goto(base + route).status == 200
                    no_overflow(page)
                page.goto(base + "/dashboard")
        page.get_by_role("button", name="Settings", exact=True).click()
        page.get_by_role("combobox", name="Appearance", exact=True).select_option("system")
        for mode in ["light", "dark"]:
            page.emulate_media(color_scheme=mode)
            expect(page.locator("html")).to_have_attribute("data-mode", mode)
        page.keyboard.press("Escape")
        assert not page.locator(".preferences").get_attribute("open")
        page.emulate_media(reduced_motion="reduce")
        assert (
            page.locator("button").first.evaluate("e => getComputedStyle(e).transitionDuration")
            == "0s"
        )
        page.goto(base + "/capture")
        page.get_by_label("Start date", exact=True).fill("2026-10-08")
        page.get_by_label("Completion date", exact=True).fill("2026-10-07")
        page.get_by_role("button", name="Save Raw Note").click()
        assert page.locator('[aria-invalid="true"]').count() > 0
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(base + "/capture")
        page.get_by_role("button", name="Settings", exact=True).click()
        expect(page.get_by_role("dialog", name="Settings", exact=True)).to_be_visible()
        no_overflow(page)
        page.screenshot(path=str(ARTIFACTS / "settings-mobile.png"), full_page=True)
        page.keyboard.press("Escape")
        page.screenshot(path=str(ARTIFACTS / "capture-mobile.png"), full_page=True)
        expect(page.locator(".navigation")).not_to_be_visible()
        page.get_by_role("button", name="Menu", exact=True).click()
        assert page.get_by_role("link", name="Overview", exact=True).is_visible()
        page.set_viewport_size({"width": 1366, "height": 768})
        page.goto(base + "/dashboard")
        expect(page.get_by_role("link", name="Overview", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Settings", exact=True)).to_be_in_viewport()
        expect(page.get_by_role("button", name="Log out", exact=True)).to_be_in_viewport()
        page.screenshot(path=str(ARTIFACTS / "navigation-laptop.png"), full_page=True)
        page.goto(base + "/dashboard")
        page.keyboard.press("Tab")
        assert page.locator(":focus").text_content() == "Skip to content"
        page.keyboard.press("Enter")
        assert page.locator(":focus").get_attribute("id") == "main"
        results["interactions"].append(
            "Theme persistence, live OS changes, Escape, reduced motion, validation, mobile menu, keyboard skip link"
        )
        assert not results["errors"], results["errors"]
        browser.close()
    (ARTIFACTS / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(
        f"PASS: {len(results['pages'])} page/viewport checks; 12 theme combinations; contrast and interaction checks. Artifacts: {ARTIFACTS}"
    )
finally:
    server.terminate()
    server.wait(timeout=15)
    log.close()
