(() => {
  const button = document.querySelector('#assist-capture');
  if (!button) return;
  const form = button.closest('form');
  const status = document.querySelector('#assist-status');
  const results = document.querySelector('#assist-results');
  const names = {title: 'Title', action: 'Action', metric: 'Metric', impact: 'Impact', supporting_narrative: 'Supporting evidence / notes', systems: 'Systems', technologies: 'Technologies', tags: 'Tags', categories: 'Categories'};
  button.addEventListener('click', async () => {
    const note = form.elements.raw_note.value;
    const provider = form.elements.provider_id.value;
    if (!note.trim()) { status.textContent = 'First describe what you did in the note above.'; form.elements.raw_note.focus(); return; }
    button.disabled = true;
    status.textContent = 'Asking your AI provider for suggestions…';
    results.replaceChildren();
    const original = Object.fromEntries(Object.keys(names).map(name => [name, form.elements[name].value]));
    async function generate(confirmed = false) {
      const response = await fetch('/capture/assist', {method: 'POST', body: new URLSearchParams({csrf: form.elements.csrf.value, raw_note: note, provider_id: provider, remote_confirmation: String(confirmed)})});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Save a copy of your note before reloading and signing in.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'AI assistance is unavailable. Check AI Providers.');
      if (data.confirmation_required) {
        if (!window.confirm(`Send this note to remote provider ${data.provider}? Only this note and a factual-writing instruction are sent.\n\n${data.raw_note}`)) return null;
        return generate(true);
      }
      return data.draft;
    }
    try {
      const draft = await generate();
      if (!draft) { status.textContent = 'Canceled. Nothing was sent to the remote provider.'; return; }
      if (form.elements.raw_note.value !== note || form.elements.provider_id.value !== provider) { status.textContent = 'Your note or provider changed. Click Help me fill this out again for fresh suggestions.'; return; }
      let preserved = 0;
      for (const [name, label] of Object.entries(names)) {
        const suggested = draft[['systems', 'technologies', 'tags', 'categories'].includes(name) ? `suggested_${name}` : name];
        const value = Array.isArray(suggested) ? suggested.join(', ') : suggested;
        if (typeof value !== 'string' || !value.trim()) continue;
        const input = form.elements[name];
        if (!input.value.trim() && input.value === original[name]) {
          input.value = value; input.dispatchEvent(new Event('input', {bubbles: true}));
        } else {
          preserved++;
          const panel = document.createElement('section'); panel.className = 'panel';
          const heading = document.createElement('h3'); heading.textContent = `Suggested ${label}`;
          const text = document.createElement('p'); text.textContent = value;
          const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'secondary'; apply.textContent = `Replace ${label} with suggestion`;
          apply.onclick = () => { input.value = value; input.dispatchEvent(new Event('input', {bubbles: true})); panel.remove(); };
          panel.append(heading, text, apply); results.append(panel);
        }
      }
      for (const group of ['questions', 'placeholders', 'assumptions', 'quality_checks']) {
        if (!draft[group]?.length) continue;
        const heading = document.createElement('h3'); heading.textContent = group.replaceAll('_', ' ');
        const list = document.createElement('ul');
        draft[group].forEach(item => { const li = document.createElement('li'); li.textContent = item; list.append(li); });
        results.append(heading, list);
      }
      status.textContent = `AI suggestions filled the empty fields. Review required: confirm every claim and replace missing-information placeholders before saving as completed.${preserved ? ' Your existing text was preserved; replacement suggestions are below.' : ''}`;
    } catch (error) {
      status.textContent = error.message;
      const link = document.createElement('a'); link.href = '/providers'; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Open AI Providers (new tab)'; results.append(link);
    } finally { button.disabled = false; }
  });
})();
