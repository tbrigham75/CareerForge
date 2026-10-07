(() => {
  const button = document.querySelector('#assist-capture');
  if (!button) return;
  const form = button.closest('form');
  const status = document.querySelector('#assist-status');
  const results = document.querySelector('#assist-results');
  const answers = new Map();
  const fieldAnswers = new Map();
  const lastAI = new Map();
  const names = {title: 'Title', action: 'Action', metric: 'Metric', impact: 'Impact', supporting_narrative: 'Supporting evidence / notes', systems: 'Systems', technologies: 'Technologies', tags: 'Tags', categories: 'Categories'};
  async function assist() {
    if (button.disabled) return;
    const note = form.elements.raw_note.value;
    const provider = form.elements.provider_id.value;
    if (!note.trim()) { status.textContent = 'First describe what you did in the note above.'; form.elements.raw_note.focus(); return; }
    results.querySelectorAll('[data-question]').forEach(input => answers.set(input.dataset.question, input.value));
    form.querySelectorAll('[data-field-answer]').forEach(input => fieldAnswers.set(input.dataset.fieldAnswer, {question: input.dataset.questionText, answer: input.value}));
    const followUp = [...[...fieldAnswers].filter(([, item]) => item.answer.trim()).map(([field, item]) => `Field: ${field}\nQuestion: ${item.question}\nAnswer: ${item.answer}`), ...[...answers].filter(([, answer]) => answer.trim()).map(([question, answer]) => `Question: ${question}\nAnswer: ${answer}`)].join('\n\n');
    button.disabled = true;
    results.querySelectorAll('button, textarea').forEach(control => control.disabled = true);
    form.querySelectorAll('[data-field-answer], [data-refine-field]').forEach(control => control.disabled = true);
    status.textContent = 'Asking your AI provider for suggestions…';
    const original = Object.fromEntries(Object.keys(names).map(name => [name, form.elements[name].value]));
    async function generate(confirmed = false) {
      const response = await fetch('/capture/assist', {method: 'POST', body: new URLSearchParams({csrf: form.elements.csrf.value, raw_note: note, follow_up_answers: followUp, provider_id: provider, remote_confirmation: String(confirmed)})});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Save a copy of your note before reloading and signing in.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'AI assistance is unavailable. Check AI Providers.');
      if (data.confirmation_required) {
        if (!window.confirm(`Send this note and follow-up answers to remote provider ${data.provider}? A factual-writing instruction is also sent.\n\n${data.raw_note}\n\nFollow-up answers:\n${data.follow_up_answers || '(none)'}`)) return null;
        return generate(true);
      }
      return data.draft;
    }
    try {
      const draft = await generate();
      if (!draft) { status.textContent = 'Canceled. Nothing was sent to the remote provider.'; return; }
      if (form.elements.raw_note.value !== note || form.elements.provider_id.value !== provider) { status.textContent = 'Your note or provider changed. Click Help me fill this out again for fresh suggestions.'; return; }
      results.replaceChildren();
      form.querySelectorAll('.field-followup').forEach(section => section.remove());
      let preserved = 0;
      for (const [name, label] of Object.entries(names)) {
        const suggested = draft[['systems', 'technologies', 'tags', 'categories'].includes(name) ? `suggested_${name}` : name];
        const value = Array.isArray(suggested) ? suggested.join(', ') : suggested;
        if (typeof value !== 'string' || !value.trim()) continue;
        const input = form.elements[name];
        if ((!input.value.trim() || input.value === lastAI.get(name)) && input.value === original[name]) {
          input.value = value; input.dispatchEvent(new Event('input', {bubbles: true}));
          lastAI.set(name, value);
        } else {
          preserved++;
          const panel = document.createElement('section'); panel.className = 'panel';
          const heading = document.createElement('h3'); heading.textContent = `Suggested ${label}`;
          const text = document.createElement('p'); text.textContent = value;
          const apply = document.createElement('button'); apply.type = 'button'; apply.className = 'secondary'; apply.textContent = `Replace ${label} with suggestion`;
          apply.onclick = () => { input.value = value; lastAI.set(name, value); input.dispatchEvent(new Event('input', {bubbles: true})); panel.remove(); };
          panel.append(heading, text, apply); results.append(panel);
        }
      }
      for (const [field, question] of Object.entries(draft.field_questions || {})) {
        if (!['metric', 'impact'].includes(field)) continue;
        const section = document.createElement('section'); section.className = 'field-followup notice';
        const heading = document.createElement('h3'); heading.textContent = `Help complete ${names[field]}`;
        const label = document.createElement('label'); label.textContent = question;
        const input = document.createElement('textarea'); input.dataset.fieldAnswer = field; input.dataset.questionText = question; input.value = fieldAnswers.get(field)?.answer || ''; input.maxLength = 10000;
        const update = document.createElement('button'); update.type = 'button'; update.dataset.refineField = field; update.textContent = `Update ${names[field]} from my answer`; update.addEventListener('click', assist);
        label.append(input); section.append(heading, label, update);
        form.elements[field].closest('label').after(section);
      }
      const followUps = document.createElement('section'); followUps.className = 'panel';
      const title = document.createElement('h3'); title.textContent = 'Refine with your answers';
      const help = document.createElement('p'); help.textContent = 'Optional: answer what you know, or say “unknown.” Add corrections below. Updating refreshes untouched AI fields; your edits stay yours. Answers are used for this draft and are not saved separately.';
      followUps.append(title, help);
      const questions = [...new Set([...answers.keys(), ...(draft.questions || []).slice(0, 3), 'Additional facts or corrections'])];
      for (const question of questions) {
        const label = document.createElement('label'); label.textContent = question;
        const input = document.createElement('textarea'); input.dataset.question = question; input.value = answers.get(question) || ''; input.maxLength = 20000;
        label.append(input); followUps.append(label);
      }
      const update = document.createElement('button'); update.type = 'button'; update.textContent = 'Update suggestions with my answers'; update.addEventListener('click', assist);
      followUps.append(update); results.append(followUps);
      for (const group of ['placeholders', 'assumptions', 'quality_checks']) {
        if (!draft[group]?.length) continue;
        const heading = document.createElement('h3'); heading.textContent = {placeholders: 'Facts still needed', assumptions: 'Please verify', quality_checks: 'Review checklist'}[group];
        const list = document.createElement('ul');
        draft[group].forEach(item => { const li = document.createElement('li'); li.textContent = item; list.append(li); });
        results.append(heading, list);
      }
      status.textContent = `AI suggestions updated. Answer any follow-up questions below and click Update suggestions with my answers, or edit the fields directly. Review claims and unresolved placeholders before saving.${preserved ? ' Your edits were preserved; replacement suggestions are below.' : ''}`;
    } catch (error) {
      status.textContent = error.message;
      const link = document.createElement('a'); link.href = '/providers'; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Open AI Providers (new tab)'; results.append(link);
    } finally { button.disabled = false; results.querySelectorAll('button, textarea').forEach(control => control.disabled = false); form.querySelectorAll('[data-field-answer], [data-refine-field]').forEach(control => control.disabled = false); }
  }
  button.addEventListener('click', assist);
})();
