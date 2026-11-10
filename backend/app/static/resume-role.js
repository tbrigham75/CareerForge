(() => {
  const choice = document.getElementById('resume-role-choice');
  const manual = document.getElementById('resume-role-manual');
  const anchor = document.querySelector('select[name="anchor"]');
  const summary = document.getElementById('resume-role-summary');
  const editor = document.getElementById('resume-role-editor');
  if (!choice || !manual) return;
  function update(moveAnchor) {
    const isManual = choice.value === 'manual';
    manual.hidden = !isManual;
    manual.querySelector('input').required = isManual;
    manual.querySelector('input').disabled = !isManual;
    const option = choice.selectedOptions[0];
    if (summary) {
      summary.textContent = isManual
        ? manual.querySelector('input').value.trim() || 'Enter your current employer and role below.'
        : option?.textContent || 'Choose your current role.';
    }
    if (moveAnchor && anchor && option && option.dataset.anchor !== undefined) {
      anchor.value = option.dataset.anchor;
      const start = document.getElementById('resume-section-start');
      const end = document.getElementById('resume-section-end');
      if (start && option.dataset.start !== undefined) start.value = option.dataset.start;
      if (end && option.dataset.end !== undefined) end.value = option.dataset.end;
    }
  }
  choice.addEventListener('change', () => update(true));
  manual.querySelector('input').addEventListener('input', () => update(false));
  // A required correction inside the collapsed editor must remain reachable.
  for (const input of [choice, manual.querySelector('input')]) {
    input.addEventListener('invalid', () => {
      if (editor?.tagName === 'DETAILS') editor.open = true;
    });
  }
  update(true);
})();
