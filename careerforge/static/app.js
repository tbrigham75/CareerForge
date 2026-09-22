(() => {
  "use strict";

  let csrfToken = "";
  let heartbeatId;
  const themes = ["dark", "slate", "forest", "ocean", "sunset"];
  const $ = (id) => document.getElementById(id);
  const $$ = (selector) => Array.from(document.querySelectorAll(selector));
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;",
  }[character]));

  function localDate() {
    const now = new Date();
    const offset = now.getTimezoneOffset() * 60_000;
    return new Date(now.getTime() - offset).toISOString().slice(0, 10);
  }

  function setNotice(message, kind = "info") {
    const notice = $("notice");
    notice.textContent = message;
    notice.dataset.kind = kind;
    notice.hidden = !message;
  }

  function showElement(id, visible) {
    $(id).hidden = !visible;
  }

  async function api(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (options.body) headers["Content-Type"] = "application/json";
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    let response;
    try {
      response = await fetch(path, { ...options, headers });
    } catch (_) {
      throw new Error("CareerForge cannot reach its local service. Reopen CareerForge and try again.");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || "The request could not be completed.");
    }
    return response.status === 204 ? null : response.json();
  }

  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("careerforge-theme", theme);
    $("theme").title = `Theme: ${theme}. Select to change.`;
  }

  function activatePage(page) {
    $$("[data-view]").forEach((view) => { view.hidden = view.dataset.view !== page; });
    $$("[data-page]").forEach((button) => {
      const active = button.dataset.page === page;
      button.setAttribute("aria-current", active ? "page" : "false");
    });
    if (page === "accomplishments") void loadAccomplishments();
    if (page === "goals") void loadGoals();
    if (page === "settings") void loadProviders();
  }

  function formatDraft(draft) {
    const items = [
      ["Title", draft.title], ["Action", draft.action], ["Metric", draft.metric],
      ["Impact", draft.impact], ["Narrative", draft.supporting_narrative],
    ].filter(([, value]) => value);
    const confirmations = (draft.placeholders_requiring_confirmation || []).map(escapeHtml).join(" · ");
    const questions = (draft.follow_up_questions || []).map(escapeHtml).join(" · ");
    return `<h2>AI draft</h2>${items.map(([label, value]) => `<p><strong>${label}:</strong> ${escapeHtml(value)}</p>`).join("")}
      ${confirmations ? `<p><strong>Confirm:</strong> ${confirmations}</p>` : ""}
      ${questions ? `<p><strong>Follow up:</strong> ${questions}</p>` : ""}
      ${draft.confidence_notes ? `<p class="muted">${escapeHtml(draft.confidence_notes)}</p>` : ""}`;
  }

  async function loadAccomplishments() {
    const target = $("records");
    try {
      const records = await api("/api/accomplishments");
      target.innerHTML = records.length ? records.map((record) => `
        <article class="record-row"><div><strong>${escapeHtml(record.title || record.raw_note || record.action)}</strong>
          ${record.impact ? `<p>${escapeHtml(record.impact)}</p>` : ""}</div>
          <span>${escapeHtml(record.date_completed || "Not dated")}</span><span>${escapeHtml(record.status.replaceAll("_", " "))}</span></article>`).join("")
        : '<p class="muted empty">No accomplishments saved yet. Capture your first one on Home.</p>';
    } catch (error) { setNotice(error.message, "error"); }
  }

  async function loadGoals() {
    const target = $("goals");
    try {
      const goals = await api("/api/goals");
      target.innerHTML = goals.length ? goals.map((goal) => `<article class="panel list-item"><strong>${escapeHtml(goal.title)}</strong><p>${escapeHtml(goal.details || "No details yet.")}</p><span class="muted">${escapeHtml(goal.status)}</span></article>`).join("")
        : '<p class="muted empty">No goals saved yet.</p>';
    } catch (error) { setNotice(error.message, "error"); }
  }

  async function testProvider(id, button) {
    button.disabled = true;
    button.textContent = "Testing…";
    try {
      const result = await api(`/api/ai-providers/${id}/test`, { method: "POST" });
      setNotice(result.models?.length ? `Connected. Available models: ${result.models.join(", ")}` : "Connected to the provider.", "success");
    } catch (error) { setNotice(error.message, "error"); }
    finally { button.disabled = false; button.textContent = "Test connection"; }
  }

  async function loadProviders() {
    const target = $("providers");
    try {
      const providers = await api("/api/ai-providers");
      target.innerHTML = providers.length ? providers.map((provider) => `<article class="provider-row"><div><strong>${escapeHtml(provider.display_name)}</strong>${provider.is_default ? " <span class=\"badge\">Default</span>" : ""}<p>${escapeHtml(provider.provider_class)} · ${escapeHtml(provider.default_model)} · ${escapeHtml(provider.base_url)}</p></div><button class="secondary test-provider" data-provider-id="${escapeHtml(provider.id)}">Test connection</button></article>`).join("")
        : '<p class="muted empty">No provider saved. Add local Ollama or a remote Ollama-compatible endpoint.</p>';
      $$(".test-provider").forEach((button) => button.addEventListener("click", () => void testProvider(button.dataset.providerId, button)));
    } catch (error) { setNotice(error.message, "error"); }
  }

  async function heartbeat() {
    try { await fetch("/api/client-heartbeat", { method: "POST", keepalive: true }); } catch (_) { /* launcher will exit if the local page is gone */ }
  }

  function startHeartbeat() {
    void heartbeat();
    clearInterval(heartbeatId);
    heartbeatId = setInterval(heartbeat, 5_000);
  }

  function showAuthenticatedApp(session) {
    csrfToken = session.csrf_token;
    showElement("boot", false);
    showElement("auth", false);
    showElement("app", true);
    $("completed").value = localDate();
    startHeartbeat();
    activatePage("home");
  }

  function showAuthentication(setupRequired) {
    showElement("boot", false);
    showElement("auth", true);
    showElement("app", false);
    $("auth-copy").textContent = setupRequired
      ? "Create the local administrator account for this private archive."
      : "Sign in to your local accomplishment archive.";
    showElement("setup-form", setupRequired);
    showElement("login-form", !setupRequired);
  }

  async function boot() {
    try {
      const setup = await api("/api/setup-status");
      if (setup.setup_required) return showAuthentication(true);
      const session = await api("/api/session");
      if (!session.authenticated) return showAuthentication(false);
      showAuthenticatedApp(session);
    } catch (error) {
      $("boot").textContent = `CareerForge could not start: ${error.message}`;
    }
  }

  function formData(form) { return Object.fromEntries(new FormData(form)); }

  function bindAuthentication(formId, endpoint) {
    $(formId).addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const session = await api(endpoint, { method: "POST", body: JSON.stringify(formData(event.currentTarget)) });
        showAuthenticatedApp(session);
      } catch (error) { setNotice(error.message, "error"); }
    });
  }

  function bindEvents() {
    setTheme(localStorage.getItem("careerforge-theme") || "dark");
    $("theme").addEventListener("click", () => {
      const current = document.documentElement.dataset.theme;
      setTheme(themes[(themes.indexOf(current) + 1) % themes.length]);
    });
    $$("[data-page]").forEach((button) => button.addEventListener("click", () => activatePage(button.dataset.page)));
    $("capture-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        await api("/api/accomplishments", { method: "POST", body: JSON.stringify(formData(event.currentTarget)) });
        event.currentTarget.reset(); $("completed").value = localDate(); $("draft").hidden = true;
        setNotice("Accomplishment saved locally.", "success");
      } catch (error) { setNotice(error.message, "error"); }
    });
    $("draft-ai").addEventListener("click", async () => {
      const rawNote = new FormData($("capture-form")).get("raw_note")?.trim();
      if (!rawNote) return setNotice("Write an accomplishment note before asking AI to draft it.", "error");
      const button = $("draft-ai"); button.disabled = true; button.textContent = "Drafting…";
      try {
        const draft = await api("/api/ai-drafts", { method: "POST", body: JSON.stringify({ raw_note: rawNote }) });
        $("draft").innerHTML = formatDraft(draft); $("draft").hidden = false;
        setNotice("AI created a reviewable draft. Your original note has not been changed.", "success");
      } catch (error) { setNotice(error.message, "error"); }
      finally { button.disabled = false; button.textContent = "Draft with AI"; }
    });
    $("goal-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try { await api("/api/goals", { method: "POST", body: JSON.stringify(formData(event.currentTarget)) }); event.currentTarget.reset(); setNotice("Goal saved locally.", "success"); await loadGoals(); }
      catch (error) { setNotice(error.message, "error"); }
    });
    $("suggest-goals").addEventListener("click", async () => {
      const button = $("suggest-goals"); button.disabled = true; button.textContent = "Thinking…";
      try {
        const result = await api("/api/goals/suggestions", { method: "POST" });
        $("goal-suggestions").innerHTML = result.suggestions?.map((suggestion, index) => `<article class="suggestion"><strong>${escapeHtml(suggestion.title)}</strong><p>${escapeHtml(suggestion.details)}</p><button class="secondary use-goal" data-index="${index}">Use draft</button></article>`).join("") || '<p class="muted">No suggestions returned.</p>';
        $$(".use-goal").forEach((useButton) => useButton.addEventListener("click", () => {
          const suggestion = result.suggestions[Number(useButton.dataset.index)];
          $("goal-form").title.value = suggestion.title || ""; $("goal-form").details.value = suggestion.details || "";
          $("goal-form").scrollIntoView({ behavior: "smooth", block: "center" });
        }));
      } catch (error) { setNotice(error.message, "error"); }
      finally { button.disabled = false; button.textContent = "Suggest goals"; }
    });
    $("chat-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const message = new FormData(event.currentTarget).get("message")?.trim();
      if (!message) return;
      try {
        const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ message }) });
        const log = $("chat-log");
        if (log.querySelector(".muted")) log.innerHTML = "";
        log.insertAdjacentHTML("beforeend", `<article class="chat-turn"><strong>You</strong><p>${escapeHtml(message)}</p><strong>CareerForge AI</strong><p>${escapeHtml(result.reply)}</p></article>`);
        event.currentTarget.reset(); log.scrollTop = log.scrollHeight;
      } catch (error) { setNotice(error.message, "error"); }
    });
    $("provider-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const values = formData(event.currentTarget); values.is_default = event.currentTarget.is_default.checked;
      try { await api("/api/ai-providers", { method: "POST", body: JSON.stringify(values) }); event.currentTarget.reset(); event.currentTarget.display_name.value = "Local Ollama"; event.currentTarget.is_default.checked = true; setNotice("AI provider saved.", "success"); await loadProviders(); }
      catch (error) { setNotice(error.message, "error"); }
    });
    $("password-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      try { await api("/api/password", { method: "POST", body: JSON.stringify(formData(event.currentTarget)) }); event.currentTarget.reset(); setNotice("Password updated.", "success"); }
      catch (error) { setNotice(error.message, "error"); }
    });
    $("logout").addEventListener("click", async () => { try { await api("/api/logout", { method: "POST" }); } finally { csrfToken = ""; clearInterval(heartbeatId); location.reload(); } });
    window.addEventListener("pagehide", () => { clearInterval(heartbeatId); navigator.sendBeacon("/api/client-heartbeat"); });
  }

  bindEvents();
  void boot();
})();
