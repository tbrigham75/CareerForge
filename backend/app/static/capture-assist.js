(() => {
  const button = document.querySelector('#assist-capture');
  if (!button) return;
  const form = button.closest('form');
  const status = document.querySelector('#assist-status');
  const results = document.querySelector('#assist-results');
  const answers = new Map();
  const fieldAnswers = new Map();
  const lastAI = new Map();
  const appliedAnswers = new Map();
  async function applyFieldAnswer(field, answer) {
    if (button.disabled) return;
    const value = answer.trim();
    if (!value) {
      status.textContent = `Enter an answer for ${names[field]} first.`;
      form.querySelector(`[data-field-answer="${field}"]`)?.focus();
      return;
    }
    const input = form.elements[field];
    const original = input.value;
    const note = form.elements.raw_note.value;
    const provider = form.elements.provider_id.value;
    const question = fieldAnswers.get(field)?.question || '';
    button.disabled = true;
    form.querySelectorAll('[data-field-answer], [data-refine-field], #assist-results button, #assist-results textarea').forEach(control => control.disabled = true);
    status.textContent = `AI is wording your answer for ${names[field]}…`;
    async function rewrite(confirmed = false) {
      const response = await fetch('/capture/assist', {method: 'POST', body: new URLSearchParams({csrf: form.elements.csrf.value, raw_note: note, provider_id: provider, target_field: field, target_answer: value, target_question: question, remote_confirmation: String(confirmed)})});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Copy your work before signing in again.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'AI rewriting failed. Your fields are unchanged.');
      if (data.confirmation_required) {
        if (!window.confirm(`Send this note and answer to remote provider ${data.provider}?\n\n${data.raw_note}\n\n${data.follow_up_answers}`)) return null;
        return rewrite(true);
      }
      if (data.field !== field || typeof data.suggestion !== 'string' || !data.suggestion.trim()) throw new Error('AI returned no usable wording for this field. Please retry.');
      return data.suggestion;
    }
    try {
      const suggestion = await rewrite();
      if (!suggestion) { status.textContent = 'Canceled. Your fields are unchanged.'; return; }
      if (input.value !== original || form.elements.raw_note.value !== note || form.elements.provider_id.value !== provider) {
        status.textContent = 'Your note, provider or field changed while AI was working. Your edits were preserved; click the field update button again when ready.';
        return;
      }
      input.value = suggestion;
      form.dispatchEvent(new Event('capture-ai-applied'));
      input.dispatchEvent(new Event('input', {bubbles: true}));
      lastAI.delete(field);
      appliedAnswers.set(field, value);
      status.textContent = `AI wording was placed in ${names[field]}. No other fields changed. Review this wording, your project, and your start and completion dates before saving.`;
      input.focus();
    } catch (error) { status.textContent = error.message; }
    finally {
      button.disabled = false;
      form.querySelectorAll('[data-field-answer], [data-refine-field], #assist-results button, #assist-results textarea').forEach(control => control.disabled = false);
    }
  }
  const names = {title: 'Title', action: 'Action', metric: 'Metric', impact: 'Impact', supporting_narrative: 'Supporting evidence / notes', systems: 'Systems', technologies: 'Technologies', tags: 'Tags', categories: 'Categories'};
  async function assist() {
    if (button.disabled) return;
    const note = form.elements.raw_note.value;
    const provider = form.elements.provider_id.value;
    if (!note.trim()) { status.textContent = 'First describe what you did in the note above.'; form.elements.raw_note.focus(); return; }
    results.querySelectorAll('[data-question]').forEach(input => answers.set(input.dataset.question, input.value));
    form.querySelectorAll('[data-field-answer]').forEach(input => fieldAnswers.set(input.dataset.fieldAnswer, {question: input.dataset.questionText, answer: input.value}));
    const submittedFieldAnswers = new Map([...fieldAnswers].filter(([field, item]) => item.answer.trim() && appliedAnswers.get(field) !== item.answer.trim()).map(([field, item]) => [field, item.answer.trim()]));
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
      // Even the general refinement action must honor explicitly named answers.
      // Model output cannot reroute them into Supporting evidence / notes.
      for (const [field, answer] of submittedFieldAnswers) {
        draft[field] = answer;
        if (draft.field_questions) delete draft.field_questions[field];
      }
      let preserved = 0;
      for (const [name, label] of Object.entries(names)) {
        if (name === 'supporting_narrative' && submittedFieldAnswers.size) continue;
        const suggested = draft[['systems', 'technologies', 'tags', 'categories'].includes(name) ? `suggested_${name}` : name];
        const value = Array.isArray(suggested) ? suggested.join(', ') : suggested;
        if (typeof value !== 'string' || !value.trim()) continue;
        const input = form.elements[name];
        const isFieldAnswer = submittedFieldAnswers.has(name);
        if ((!input.value.trim() || input.value === lastAI.get(name) || isFieldAnswer) && input.value === original[name]) {
          input.value = value; input.dispatchEvent(new Event('input', {bubbles: true}));
          if (isFieldAnswer) { lastAI.delete(name); appliedAnswers.set(name, value); } else lastAI.set(name, value);
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
        const update = document.createElement('button'); update.type = 'button'; update.dataset.refineField = field; update.textContent = `Update ${names[field]} from my answer`;
        const hint = document.createElement('p'); hint.className = 'muted'; hint.textContent = `AI will polish your answer and update only ${names[field]}. Other fields will not change.`;
        update.addEventListener('click', () => {
          fieldAnswers.set(field, {question, answer: input.value});
          applyFieldAnswer(field, input.value);
        });
        label.append(input); section.append(heading, label, hint, update);
        form.elements[field].closest('label').after(section);
      }
      const activeQuestions = (draft.questions || []).slice(0, 3);
      const followUps = document.createElement('details'); followUps.className = 'panel';
      followUps.open = activeQuestions.length > 0;
      const title = document.createElement('summary'); title.textContent = activeQuestions.length ? 'A detail that would help' : 'Add details or corrections (optional)';
      const help = document.createElement('p'); help.textContent = 'Add facts you want included, then update the suggestions. Your original note and manual edits are preserved.';
      followUps.append(title, help);
      const questions = [...new Set([...answers.keys(), ...activeQuestions, 'Additional facts or corrections'])];
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
      const hasQuestions = activeQuestions.length || Object.keys(draft.field_questions || {}).length;
      form.dispatchEvent(new Event('capture-ai-applied'));
      status.textContent = `Your accomplishment draft is ready to review. Confirm your project, start date, and completion date below before saving.${hasQuestions ? ' A specific question appears beside any field that needs more information; you can leave it unanswered.' : ' You can edit the fields directly or optionally add more details.'}${preserved ? ' Your edits were preserved; replacement suggestions are below.' : ''}`;
    } catch (error) {
      status.textContent = error.message;
      const link = document.createElement('a'); link.href = '/providers'; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Open AI Providers (new tab)'; results.append(link);
    } finally { button.disabled = false; results.querySelectorAll('button, textarea').forEach(control => control.disabled = false); form.querySelectorAll('[data-field-answer], [data-refine-field]').forEach(control => control.disabled = false); }
  }
  button.addEventListener('click', assist);
})();
