(() => {
  const theme = document.querySelector('#theme-choice');
  const appearance = document.querySelector('#appearance-choice');
  const preferences = window.careerforgeTheme.get();
  theme.value = preferences.theme;
  appearance.value = preferences.appearance;
  function updateTheme() {
    const saved = window.careerforgeTheme.set(theme.value, appearance.value);
    document.querySelector('#theme-feedback').textContent = saved ? 'Preferences saved.' : 'Applied for this page. Browser storage is unavailable.';
  }
  theme.addEventListener('change', updateTheme);
  appearance.addEventListener('change', updateTheme);
  const menu = document.querySelector('.navigation');
  const mobile = matchMedia('(max-width: 900px)');
  function resizeNavigation() { if (menu) menu.open = !mobile.matches; }
  mobile.addEventListener('change', resizeNavigation);
  resizeNavigation();
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') document.querySelectorAll('.preferences[open]').forEach(item => {
      item.open = false;
      item.querySelector('summary').focus();
    });
  });
  const heading = document.querySelector('main h1');
  if (heading) document.title = `${heading.textContent.trim()} · CareerForge`;
  document.querySelectorAll('main table').forEach(table => {
    const wrapper = document.createElement('div');
    wrapper.className = 'table-scroll';
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', `${heading?.textContent.trim() || 'Data'} table; scroll horizontally for more columns`);
    table.before(wrapper); wrapper.append(table);
    table.querySelectorAll('th').forEach(th => th.scope = 'col');
  });
  document.querySelectorAll('main form').forEach(form => {
    const feedback = document.createElement('p');
    feedback.className = 'form-feedback'; feedback.setAttribute('role', 'status'); form.append(feedback);
    form.addEventListener('invalid', event => {
      event.target.setAttribute('aria-invalid', 'true');
      feedback.textContent = 'Please check the highlighted field before continuing.';
    }, true);
    form.addEventListener('input', event => {
      if (event.target.validity?.valid) event.target.removeAttribute('aria-invalid');
      feedback.textContent = '';
    });
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      // Preserve submitter values used by the server for action selection.
      form.setAttribute('aria-busy', 'true'); feedback.textContent = 'Working…';
      setTimeout(() => { form.removeAttribute('aria-busy'); feedback.textContent = ''; }, 8000);
    });
  });
  window.addEventListener('pageshow', () => document.querySelectorAll('[aria-busy]').forEach(form => {
    form.removeAttribute('aria-busy'); form.querySelector('.form-feedback').textContent = '';
  }));
})();
