(() => {
  const data = document.getElementById('resume-preview-data');
  if (!data) return;
  const {paragraphs, proposal} = JSON.parse(data.textContent);
  const form = document.querySelector('form[action$="/review"]');
  const output = document.getElementById('resume-live-preview');
  const words = text => text.trim() ? text.trim().split(/\s+/u).length : 0;
  function refresh() {
    const replacements = new Map(), removed = new Set(), additions = [];
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
  }
  form.addEventListener('input', refresh);
  document.getElementById('resume-show-changes').addEventListener('change', refresh);
  refresh();
})();
