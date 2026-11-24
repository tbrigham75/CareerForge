(() => {
  const form = document.getElementById('self-input-delete-selection');
  if (!form) return;
  const boxes = [...form.querySelectorAll('[name="assessment_ids"]')];
  const all = document.getElementById('self-input-select-all');
  const button = document.getElementById('self-input-delete-selected');
  function refresh() {
    const count = boxes.filter(box => box.checked).length;
    all.checked = count === boxes.length;
    all.indeterminate = count > 0 && count < boxes.length;
    button.disabled = count === 0;
    button.textContent = `Delete selected (${count})`;
    document.getElementById('self-input-selection-count').textContent = `${count} selected`;
  }
  document.getElementById('self-input-select-all-label').hidden = false;
  document.getElementById('self-input-selection-count').hidden = false;
  all.addEventListener('change', () => {
    boxes.forEach(box => { box.checked = all.checked; });
    refresh();
  });
  boxes.forEach(box => box.addEventListener('change', refresh));
  window.addEventListener('pageshow', refresh);
  refresh();
})();
