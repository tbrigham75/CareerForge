(() => {
  const form = document.querySelector('form[action="/capture"]');
  if (!form) return;
  const project = form.elements.project_id;
  const reminder = document.querySelector('#capture-context-reminder');
  const feedback = document.querySelector('#capture-context-feedback');
  const fields = ['project_id', 'date_started', 'date_completed'];
  function reviewNeeded() {
    reminder.hidden = false;
    feedback.textContent = '';
    for (const name of fields) {
      const wrapper = document.querySelector(`[data-review-field="${name}"]`);
      wrapper.classList.add('needs-review');
      const hint = wrapper.querySelector('.capture-review-hint');
      if (hint) hint.hidden = false;
    }
  }
  form.addEventListener('capture-ai-applied', reviewNeeded);
  document.querySelector('#confirm-capture-context').onclick = () => {
    const missing = fields.find(name => !form.elements[name].value || !form.elements[name].checkValidity());
    if (missing) {
      feedback.textContent = 'Choose a project and valid dates before confirming. Raw notes can still be saved without a project.';
      form.elements[missing].focus(); return;
    }
    for (const wrapper of form.querySelectorAll('.capture-review-field')) {
      wrapper.classList.remove('needs-review');
      const hint = wrapper.querySelector('.capture-review-hint');
      if (hint) hint.hidden = true;
    }
    feedback.textContent = 'Project and dates reviewed. You can still change them before saving.';
  };
  for (const name of fields) form.elements[name].addEventListener('change', () => {
    if (!reminder.hidden) reviewNeeded();
  });
  function requireProject(completed) {
    project.required = completed;
    if (completed && !project.value) {
      reviewNeeded();
      feedback.textContent = 'Select a project to save a completed accomplishment.';
      project.setAttribute('aria-invalid', 'true');
    }
  }
  form.querySelectorAll('button[name="action_choice"]').forEach(button => button.addEventListener('click', () => requireProject(button.value === 'completed')));
  form.addEventListener('submit', event => {
    requireProject(event.submitter?.value === 'completed');
    if (project.required && !project.value) { event.preventDefault(); project.reportValidity(); }
  });
  const refresh = document.querySelector('#refresh-capture-projects');
  refresh.onclick = async () => {
    refresh.disabled = true;
    const status = document.querySelector('#capture-project-status');
    status.textContent = 'Refreshing projects…';
    try {
      const response = await fetch('/capture/projects');
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('Unable to refresh projects. Your form is unchanged; check that you are signed in.');
      const data = await response.json();
      const previous = project.value;
      project.replaceChildren(new Option('Select a project', ''), ...data.projects.map(item => new Option(item.name, item.id)));
      project.value = data.projects.some(item => item.id === previous) ? previous : '';
      if (project.value !== previous) project.dispatchEvent(new Event('change', {bubbles: true}));
      status.textContent = data.projects.length ? 'Projects refreshed. Choose the project for this accomplishment.' : 'No projects yet. Use Manage projects to create one, then refresh here.';
    } catch (error) { status.textContent = error.message; }
    finally { refresh.disabled = false; }
  };
})();
