(() => {
  const form = document.querySelector('#report-form');
  if (!form) return;
  const templates = JSON.parse(document.querySelector('#report-template-data').textContent);
  const selector = form.elements.template_id;
  const templateName = document.querySelector('#template-name');
  const status = document.querySelector('#template-status');
  const validation = document.querySelector('#report-validation');
  const settings = ['title', 'content', 'report_type', 'output_filename', 'layout'];
  let destination = null;
  const destinationStatus = document.querySelector('#report-destination-status');
  const clearDestination = document.querySelector('#clear-report-destination');
  function resetDestination() {
    destination = null; clearDestination.hidden = true;
    destinationStatus.textContent = 'Using your browser’s normal download location.';
  }
  clearDestination.onclick = resetDestination;
  form.elements.output_filename.addEventListener('input', resetDestination);
  document.querySelector('#choose-report-destination').onclick = async () => {
    if (!window.showSaveFilePicker) {
      destinationStatus.textContent = 'This browser does not provide a save-location picker here. Enable “Ask where to save each file” in browser download settings, then generate the report. No server path is used.';
      return;
    }
    try {
      const handle = await window.showSaveFilePicker({suggestedName: form.elements.output_filename.value, types: [{description: 'Word document', accept: {'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx']}}]});
      destination = handle; form.elements.output_filename.value = handle.name;
      clearDestination.hidden = false;
      destinationStatus.textContent = `Selected ${handle.name} in the location you chose. Generate the report to write it there.`;
    } catch (error) { if (error.name !== 'AbortError') destinationStatus.textContent = `Could not select a destination: ${error.message}. Previous selection unchanged.`; }
  };
  const baseline = Object.fromEntries(settings.map(key => [key, form.dataset.preservedInput === 'true' ? null : form.elements[key].value]));
  let selectedTemplate = selector.value;
  const updateButtons = () => {
    document.querySelector('#update-template').disabled = !selector.value;
    document.querySelector('#delete-template').disabled = !selector.value;
  };
  updateButtons();
  if (templates[selectedTemplate]) templateName.value = templates[selectedTemplate].name;
  selector.addEventListener('change', () => {
    const template = templates[selector.value];
    if (template) {
      const entries = Object.entries(template.settings).filter(([key]) => settings.includes(key));
      if (entries.some(([key, value]) => form.elements[key].value !== baseline[key] && form.elements[key].value !== value) && !confirm('Applying this template will replace report settings you edited. Continue? Your accomplishment selections will not change.')) {
        selector.value = selectedTemplate;
        return;
      }
      for (const [key, value] of entries) {
        if (key === 'output_filename' && form.elements[key].value !== value) resetDestination();
        form.elements[key].value = value; baseline[key] = value;
      }
      templateName.value = template.name;
      status.textContent = 'Template applied. Review and edit the report settings before generating.';
    }
    selectedTemplate = selector.value;
    updateButtons();
  });
  async function manage(action) {
    const id = selector.value;
    if (action !== 'save' && !id) return;
    if (action === 'delete' && !confirm('Delete this template? Generated reports and current settings will remain unchanged.')) return;
    if (action === 'update' && !confirm('Replace this template with the current report settings?')) return;
    const body = new URLSearchParams({csrf: form.elements.csrf.value, name: templateName.value});
    for (const key of settings) body.set(key, form.elements[key].value);
    const buttons = ['save-template', 'update-template', 'delete-template'].map(key => document.getElementById(key));
    buttons.forEach(button => button.disabled = true); selector.disabled = true;
    status.textContent = 'Saving template changes…';
    try {
      const response = await fetch(action === 'save' ? '/reports/templates' : `/reports/templates/${encodeURIComponent(id)}/${action}`, {method: 'POST', headers: {Accept: 'application/json'}, body});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Your settings remain here; copy them before signing in again.');
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Template could not be saved. Your settings are unchanged.');
      if (action === 'delete') {
        delete templates[id]; selector.querySelector(`option[value="${CSS.escape(id)}"]`)?.remove(); selector.value = ''; selectedTemplate = '';
        status.textContent = 'Template deleted. Report settings and selections are unchanged.';
      } else {
        templates[data.id] = data;
        let option = [...selector.options].find(item => item.value === data.id);
        if (!option) { option = new Option(data.name, data.id); selector.add(option); }
        option.textContent = data.name; selector.value = data.id; selectedTemplate = data.id;
        status.textContent = 'Template saved. It will be available after reloading.';
      }
    } catch (error) { status.textContent = error.message; }
    finally { selector.disabled = false; buttons.forEach(button => button.disabled = false); updateButtons(); }
  }
  for (const action of ['save', 'update', 'delete']) document.querySelector(`#${action}-template`).onclick = () => manage(action);
  const rows = [...document.querySelectorAll('[data-report-record]')];
  function scope() {
    const query = form.elements.query.value.trim().toLowerCase();
    const start = form.elements.date_from.value;
    const end = form.elements.date_to.value;
    form.elements.date_to.setCustomValidity(start && end && start > end ? 'End date must be on or after start date.' : '');
    let total = 0, count = 0;
    for (const row of rows) {
      const inScope = row.dataset.search.toLowerCase().includes(query) && (!start || row.dataset.date >= start) && (!end || (row.dataset.date && row.dataset.date <= end));
      row.hidden = !inScope;
      const checkbox = row.querySelector('input');
      checkbox.disabled = !inScope;
      if (inScope) { total++; if (checkbox.checked) count++; }
    }
    document.querySelector('#report-selection-count').textContent = `${count} selected of ${total} eligible accomplishments`;
    validation.textContent = count ? '' : 'Select at least one accomplishment to generate a report.';
    return count;
  }
  for (const key of ['query', 'date_from', 'date_to']) form.elements[key].addEventListener('input', scope);
  rows.forEach(row => row.querySelector('input').addEventListener('change', scope));
  for (const [id, checked] of [['select-all-records', true], ['deselect-all-records', false]]) document.getElementById(id).onclick = () => { rows.filter(row => !row.hidden).forEach(row => row.querySelector('input').checked = checked); scope(); };
  form.addEventListener('submit', async event => {
    if (!scope()) { event.preventDefault(); validation.scrollIntoView({block: 'center'}); return; }
    if (!destination) return;
    event.preventDefault();
    const handle = destination;
    const button = document.querySelector('#generate-report'); button.disabled = true;
    destinationStatus.textContent = 'Generating and saving your report…';
    try {
      const response = await fetch('/reports', {method: 'POST', body: new FormData(form)});
      if (!response.ok || !response.headers.get('content-type')?.includes('wordprocessingml.document')) {
        const html = new DOMParser().parseFromString(await response.text(), 'text/html');
        throw new Error(html.querySelector('[role="alert"]')?.textContent || 'Report generation failed or your session expired. Your settings and selections are preserved.');
      }
      const blob = await response.blob();
      const writable = await handle.createWritable();
      try { await writable.write(blob); await writable.close(); }
      catch (error) { await writable.abort().catch(() => {}); throw error; }
      destinationStatus.textContent = `Saved ${handle.name} to your chosen location. A server copy is also available in Generated reports after refreshing.`;
    } catch (error) { destinationStatus.textContent = `${error.message} You can choose another location or use normal downloads. A generated server copy, if created, remains available in Reports.`; }
    finally { button.disabled = false; }
  });
  scope();
})();
