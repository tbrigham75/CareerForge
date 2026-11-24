(() => {
  const root = document.querySelector('.resume-workspace');
  if (!root) return;
  const inventoryButtons = [...root.querySelectorAll('[data-inventory]')];
  const panels = [...root.querySelectorAll('[data-inventory-panel]')];
  function showInventory(name) {
    inventoryButtons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.inventory === name)));
    panels.forEach(panel => { panel.hidden = panel.dataset.inventoryPanel !== name; });
  }
  inventoryButtons.forEach(button => button.addEventListener('click', () => showInventory(button.dataset.inventory)));
  showInventory('ready');

  const layout = root.querySelector('.resume-review-layout');
  const switcher = root.querySelector('.resume-mobile-switch');
  if (layout && switcher) {
    layout.classList.add('resume-view-enabled');
    switcher.hidden = false;
    function showView(name) {
      layout.dataset.view = name;
      switcher.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.resumeView === name)));
    }
    switcher.querySelectorAll('button').forEach(button => button.addEventListener('click', () => showView(button.dataset.resumeView)));
    root.querySelectorAll('[data-resume-card-link]').forEach(link => link.addEventListener('click', () => showView('suggestions')));
  }
  root.querySelectorAll('time[datetime]').forEach(time => {
    const date = new Date(time.dateTime);
    if (!Number.isNaN(date.getTime())) time.textContent = date.toLocaleString();
  });
  let generating = false;
  const forms = [document.getElementById('resume-review'), document.getElementById('resume-generate')].filter(Boolean);
  forms.forEach(form => {
    form.addEventListener('invalid', event => {
      if (layout) {
        layout.dataset.view = 'suggestions';
        switcher.querySelectorAll('button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.resumeView === 'suggestions')));
      }
      for (let parent = event.target.parentElement; parent && parent !== form; parent = parent.parentElement) {
        if (parent.tagName === 'DETAILS') parent.open = true;
      }
    }, true);
    form.addEventListener('submit', event => {
      const action = event.submitter?.getAttribute('formaction') || form.getAttribute('action');
      if (generating) { event.preventDefault(); return; }
      if (!action.endsWith('/update')) return;
      generating = true;
      root.setAttribute('aria-busy', 'true');
      document.getElementById('resume-generation-status').textContent = 'Reviewing accomplishments with your local AI. Your existing draft is being kept. This may take a moment.';
      // Leave controls enabled so the browser submits their names and values.
    });
  });
  window.addEventListener('pageshow', () => {
    generating = false;
    root.removeAttribute('aria-busy');
    const status = document.getElementById('resume-generation-status');
    if (status) status.textContent = '';
  });
})();
