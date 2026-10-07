(() => {
  const triggers = document.querySelectorAll('[data-browse]');
  if (!triggers.length) return;
  const dialog = document.createElement('dialog');
  dialog.className = 'file-browser';
  dialog.setAttribute('aria-labelledby', 'browser-title');
  dialog.innerHTML = `<div class="page-heading"><h2 id="browser-title">Browse computer</h2><button type="button" class="secondary" data-close>Cancel</button></div>
    <p class="muted">Choose a location on the computer running CareerForge. Selection only fills the form.</p>
    <label for="browser-drive">Drive / starting location</label><select id="browser-drive"></select>
    <label for="browser-location">Current folder</label><div class="path-control"><input id="browser-location"><button type="button" class="secondary" data-go>Go</button></div>
    <div class="browser-toolbar"><button type="button" class="secondary" data-up>Up one folder</button><button type="button" data-select>Use this folder</button></div>
    <p role="status" data-status></p><div class="browser-entries" aria-label="Folders and documents"></div>
    <div class="browser-toolbar"><button type="button" class="secondary" data-prev>Previous</button><button type="button" class="secondary" data-next>Next</button></div>`;
  document.body.append(dialog);
  const location = dialog.querySelector('#browser-location');
  const drives = dialog.querySelector('#browser-drive');
  const status = dialog.querySelector('[data-status]');
  const entries = dialog.querySelector('.browser-entries');
  const useFolder = dialog.querySelector('[data-select]');
  let trigger, target, kind, repository, current, parent, previous, next, sequence = 0;
  const controls = () => dialog.querySelectorAll('button:not([data-close]), input, select');
  function message(text, error = false) { status.textContent = text; status.className = error ? 'notice error' : 'muted'; }
  async function request(path, select = false, offset = 0) {
    const id = ++sequence;
    controls().forEach(control => control.disabled = true);
    dialog.setAttribute('aria-busy', 'true');
    message('Loading…');
    try {
      const body = new URLSearchParams({csrf: trigger.closest('form').querySelector('[name="csrf"]').value, kind, path, repository, select_path: String(select), offset: String(offset)});
      const response = await fetch('/files/browse', {method: 'POST', body});
      if (!response.headers.get('content-type')?.includes('application/json')) throw new Error('Your session may have expired. Reload the page and sign in again.');
      const data = await response.json();
      if (id !== sequence || !dialog.open) return;
      if (!response.ok) throw new Error(data.error || 'Unable to browse this location.');
      if (select) {
        target.value = data.selected;
        target.dispatchEvent(new Event('input', {bubbles: true}));
        target.dispatchEvent(new Event('change', {bubbles: true}));
        dialog.close();
        return;
      }
      current = data.path; parent = data.parent; previous = data.previous; next = data.next;
      location.value = current;
      drives.replaceChildren(...data.roots.map(root => new Option(root, root)));
      drives.selectedIndex = data.roots.findIndex(root => current.toLowerCase().startsWith(root.toLowerCase()));
      entries.replaceChildren();
      for (const entry of data.entries) {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'secondary browser-entry';
        button.textContent = `${entry.folder ? 'Folder' : 'ODT file'} · ${entry.name}`;
        button.addEventListener('click', () => request(entry.path, !entry.folder));
        entries.append(button);
      }
      message(data.entries.length ? `${data.entries.length} items shown. ${kind === 'odt' ? 'Choose a document to select it.' : 'Open a folder, then choose Use this folder.'}` : 'No matching items in this folder.');
    } catch (error) {
      if (id === sequence && dialog.open) message(error.message, true);
    } finally {
      if (id === sequence) {
        controls().forEach(control => control.disabled = false);
        useFolder.disabled = !current;
        dialog.querySelector('[data-up]').disabled = !parent;
        dialog.querySelector('[data-prev]').disabled = previous == null;
        dialog.querySelector('[data-next]').disabled = next == null;
        dialog.removeAttribute('aria-busy');
      }
    }
  }
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.addEventListener('close', () => { sequence++; trigger?.focus(); });
  dialog.querySelector('[data-go]').onclick = () => request(location.value);
  location.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); request(location.value); } });
  drives.onchange = () => request(drives.value);
  dialog.querySelector('[data-up]').onclick = () => request(parent);
  dialog.querySelector('[data-prev]').onclick = () => request(current, false, previous);
  dialog.querySelector('[data-next]').onclick = () => request(current, false, next);
  useFolder.onclick = () => request(current, true);
  for (const button of triggers) button.addEventListener('click', () => {
    trigger = button; kind = button.dataset.browse;
    target = document.getElementById(button.dataset.target);
    repository = button.closest('form').querySelector('[name="repository_path"]')?.value.trim() || '';
    current = parent = previous = next = null;
    entries.replaceChildren(); location.value = ''; drives.replaceChildren();
    useFolder.hidden = kind === 'odt';
    dialog.querySelector('#browser-title').textContent = {repository: 'Choose a Git repository', subdirectory: 'Choose an export folder', odt: 'Choose an ODT document'}[kind];
    dialog.showModal();
    if (kind === 'subdirectory' && !repository) {
      message('Choose or enter a repository folder first.', true);
      controls().forEach(control => control.disabled = true);
      return;
    }
    request(kind === 'subdirectory' ? repository : target.value.trim());
  });
})();
