(() => {
  const data = document.getElementById('resume-preview-data');
  if (!data) return;
  const {paragraphs, proposal, stale = []} = JSON.parse(data.textContent);
  const form = document.querySelector('form[action$="/review"]');
  const output = document.getElementById('resume-live-preview');
  const words = text => text.trim() ? text.trim().split(/\s+/u).length : 0;
  function refresh() {
    const replacements = new Map(), removed = new Set(), additions = [];
    const sourceOwners = new Map(), targetOwners = new Map(), problems = new Set();
    let count = 0;
    proposal.bullets.forEach((change, i) => {
      if (!form.querySelector(`[name="selected"][value="${i}"]`)?.checked) return;
      count++;
      if (stale.includes(i)) problems.add(`Suggestion ${i + 1} uses an outdated source. Deselect it and request fresh wording.`);
      for (const [keys, owners, label] of [[change.source_ids || [], sourceOwners, 'the same accomplishment'], [change.targets || [], targetOwners, 'the same existing paragraph']]) {
        for (const key of new Set(keys)) {
          if (owners.has(key)) problems.add(`Suggestions ${owners.get(key) + 1} and ${i + 1} use ${label}. Choose one alternative.`);
          else owners.set(key, i);
        }
      }
    });
    document.getElementById('resume-selected-count').textContent = String(count);
    const feedback = document.getElementById('resume-selection-feedback');
    feedback.textContent = [...problems].join(' ');
    feedback.classList.toggle('notice', problems.size > 0);
    feedback.classList.toggle('warning', problems.size > 0);
    for (const button of document.querySelectorAll('button[form="resume-review"][value="save"], #resume-review button[value="save"], #resume-review button[value="render"]')) button.disabled = problems.size > 0;
    if (problems.size) {
      output.replaceChildren();
      const message = document.createElement('p');
      message.textContent = 'Preview paused: resolve the selection conflicts. You can still save your draft.';
      output.append(message);
      document.getElementById('resume-length-summary').textContent = [...problems].join(' ');
      return;
    }
    proposal.bullets.forEach((change, i) => {
      if (!form.querySelector(`[name="selected"][value="${i}"]`)?.checked) return;
      const value = form.querySelector(`[name="bullet_${i}"]`).value.trim();
      const targets = [...(change.targets || [])].sort((a,b) => a-b);
      if ((change.kind || 'add') === 'add') additions.push(value);
      else {
        targets.forEach(t => removed.add(t));
        if (change.kind !== 'remove') replacements.set(targets[0], value);
      }
    });
    const show = document.getElementById('resume-show-changes').checked;
    output.replaceChildren();
    const final = [];
    function line(value, label = '') {
      const p = document.createElement('p');
      if (show && label) { const tag = document.createElement('strong'); tag.textContent = label + ': '; p.append(tag); }
      p.append(document.createTextNode(value)); output.append(p);
    }
    paragraphs.forEach((value, i) => {
      if (show && removed.has(i)) line(value, 'Removed');
      if (replacements.has(i)) { final.push(replacements.get(i)); line(replacements.get(i), 'Replacement'); }
      else if (!removed.has(i)) { final.push(value); line(value); }
      if (i === proposal.anchor) additions.forEach(text => {final.push(text); line(text, 'New');});
    });
    const start = proposal.start ?? proposal.anchor, end = proposal.end ?? paragraphs.length;
    const before = words(paragraphs.slice(start,end).join(' '));
    const after = before + words(final.join(' ')) - words(paragraphs.join(' '));
    document.getElementById('resume-length-summary').textContent = `Section: ${before} → ${after} words. Goal: ${proposal.budget} words.${after > proposal.budget ? ' Over goal — choose fewer changes or explicitly allow extra length.' : ''}`;
    const save = document.querySelector('button[form="resume-review"][value="save"]');
    if (save) save.disabled = after > proposal.budget && !form.querySelector('[name="allow_growth"]').checked;
  }
  form.addEventListener('input', refresh);
  document.getElementById('resume-show-changes').addEventListener('change', refresh);
  refresh();
})();
