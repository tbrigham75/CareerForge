(() => {
  fetch('/taxonomy/suggestions').then(response => response.ok ? response.json() : {}).then(groups => {
    for (const [field, names] of Object.entries(groups)) {
      const input = document.querySelector(`input[name="${field}"]`);
      if (!input || !Array.isArray(names)) continue;
      const list = document.createElement('datalist');
      list.id = `suggest-${field}`;
      input.setAttribute('list', list.id);
      input.after(list);
      const refresh = () => {
        const cut = input.value.lastIndexOf(',');
        const prefix = cut < 0 ? '' : `${input.value.slice(0, cut + 1)} `;
        const used = input.value.slice(0, Math.max(0, cut)).split(',').map(v => v.trim().toLowerCase());
        list.replaceChildren(...names.filter(name => !used.includes(name.toLowerCase())).map(name => new Option(prefix + name)));
      };
      input.addEventListener('input', refresh);
      refresh();
    }
  }).catch(() => {}); // New labels remain usable if suggestions are unavailable.
})();
