(() => {
  const form = document.querySelector('#document-export-form');
  if (!form) return;
  const boxes = [...form.querySelectorAll('[name="record_ids"]')];
  const count = document.querySelector('#export-count');
  const update = () => { count.textContent = `${boxes.filter(box => box.checked).length} selected`; };
  form.querySelectorAll('[data-export-select]').forEach(button => button.addEventListener('click', () => {
    boxes.forEach(box => { box.checked = button.dataset.exportSelect === 'true'; }); update();
  }));
  boxes.forEach(box => box.addEventListener('change', update));
  form.addEventListener('submit', event => {
    if (!boxes.some(box => box.checked)) {
      event.preventDefault(); count.textContent = 'Select at least one accomplishment.'; boxes[0]?.focus();
    }
  });
  update();
})();
