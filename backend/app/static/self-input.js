(() => {
  const form = document.getElementById('self-input-review');
  if (!form) return;
  const preview = document.getElementById('self-preview');
  function refresh() {
    const sections = [...form.querySelectorAll('.self-section')].map(section => {
      const paragraphs = [...section.querySelectorAll('[data-narrative]')].map(field => field.value.trim()).filter(Boolean);
      section.querySelector('[data-empty-section-note]').hidden = paragraphs.length > 0;
      section.querySelector('[data-fill-section]').hidden = paragraphs.length > 0;
      if (!section.querySelector('[data-section-inclusion]').checked) return '';
      return paragraphs.length ? section.querySelector('h2').textContent + '\n' + paragraphs.join('\n\n') : '';
    }).filter(Boolean);
    preview.value = sections.join('\n\n');
    const characters = [...preview.value].length;
    const words = preview.value.trim() ? preview.value.trim().split(/\s+/u).length : 0;
    const limit = Number(form.elements.character_limit.value) || 0;
    const status = document.getElementById('self-length');
    status.textContent = `${words} words · ${characters} characters${limit ? ` / ${limit} limit` : ''}.${limit && characters > limit ? ' Over your limit. Shorten the text or explicitly allow the extra length before approving.' : ''}`;
    status.classList.toggle('notice', limit > 0 && characters > limit);
    status.classList.toggle('warning', limit > 0 && characters > limit);
  }
  form.addEventListener('input', refresh);
  form.addEventListener('change', event => {
    refresh();
    if (!event.target.matches('[data-section-inclusion]')) return;
    const section = event.target.closest('.self-section');
    const hasText = [...section.querySelectorAll('[data-narrative]')].some(field => field.value.trim());
    const status = document.getElementById('self-inclusion-status');
    const title = section.querySelector('h2').textContent;
    if (event.target.checked && !hasText) {
      status.textContent = `${title} has no text yet. Use Generate all sections or Write missing sections to prepare the writing, then choose what to include.`;
    } else {
      status.textContent = event.target.checked
        ? `${title} added to the combined draft below. Save draft to keep your choice.`
        : `${title} removed from the combined draft. Its section text is kept. Save draft to keep your choice.`;
    }
  });
  form.addEventListener('input', event => {
    const field = event.target;
    if (field.matches('[data-narrative], [name^="proposal_"], [name="locked"], [name="style"], [name="length"], [name="character_limit"], [name="voice_sample"], [name="review_goals"]')) {
      const apply = document.getElementById('self-use-selection');
      if (apply) apply.disabled = true;
      const stale = document.getElementById('self-selection-stale');
      if (stale) stale.hidden = false;
    }
  });
  const copy = document.getElementById('self-copy');
  copy.hidden = false;
  copy.addEventListener('click', async () => {
    refresh();
    try {
      await navigator.clipboard.writeText(preview.value);
      document.getElementById('self-copy-status').textContent = 'Draft text copied. Review it before submitting.';
    } catch {
      preview.focus(); preview.select();
      document.getElementById('self-copy-status').textContent = 'Text selected. Press Ctrl+C or use your device’s Copy action.';
    }
  });
  form.addEventListener('invalid', event => {
    for (let parent = event.target.parentElement; parent && parent !== form; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
  }, true);
  let submitting = false;
  let progressTimer;
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    submitting = true;
    if (event.submitter?.value.startsWith('generate') || event.submitter?.value.startsWith('questions:') || event.submitter?.value.startsWith('fill:') || event.submitter?.value === 'recommend') {
      const panel = document.getElementById('self-ai-progress');
      panel.hidden = false;
      panel.focus();
      panel.scrollIntoView({block: 'center'});
      const started = performance.now();
      if (event.submitter.value.startsWith('fill:')) {
        panel.querySelector('[role="status"]').textContent = 'Writing the selected section from your evidence. It will be added to the draft when ready; your existing text is kept.';
      }
      progressTimer = window.setInterval(() => {
        const elapsed = (performance.now() - started) / 1000;
        document.getElementById('self-ai-elapsed').textContent = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${(elapsed % 60).toFixed(1).padStart(4, '0')}`;
      }, 100);
      document.getElementById('self-generation-status').textContent = event.submitter.value === 'recommend'
        ? 'Reviewing the sections together to suggest a clear, focused assessment. Your text and checkbox choices are saved and will stay unchanged.'
        : 'Reading the selected evidence, writing proposals and reviewing section selection with your local AI. Large selections can take several minutes. Your draft is saved before generation.';
    }
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    window.clearInterval(progressTimer);
    document.getElementById('self-ai-progress').hidden = true;
  });
  document.querySelectorAll('.self-input-workspace time').forEach(time => {
    const value = new Date(time.dateTime);
    if (!Number.isNaN(value.getTime())) time.textContent = value.toLocaleString();
  });
  refresh();
})();
