/* Run before CSS and body paint to avoid a flash of the wrong theme. */
(() => {
  const themes = ['slate', 'ocean', 'emerald', 'violet', 'amber', 'rose'];
  const appearances = ['light', 'dark', 'system'];
  const system = matchMedia('(prefers-color-scheme: dark)');
  let theme = 'slate', appearance = 'system';
  try {
    const saved = JSON.parse(localStorage.getItem('careerforge-style') || '{}');
    if (themes.includes(saved.theme)) theme = saved.theme;
    if (appearances.includes(saved.appearance)) appearance = saved.appearance;
  } catch (_) { /* Defaults work when storage is unavailable. */ }
  function apply() {
    document.documentElement.dataset.theme = theme;
    document.documentElement.dataset.mode = appearance === 'system' ? (system.matches ? 'dark' : 'light') : appearance;
    document.documentElement.style.colorScheme = document.documentElement.dataset.mode;
  }
  window.careerforgeTheme = {
    get: () => ({ theme, appearance }),
    set(nextTheme, nextAppearance) {
      if (themes.includes(nextTheme)) theme = nextTheme;
      if (appearances.includes(nextAppearance)) appearance = nextAppearance;
      apply();
      try { localStorage.setItem('careerforge-style', JSON.stringify({ theme, appearance })); return true; }
      catch (_) { return false; }
    }
  };
  system.addEventListener('change', apply);
  apply();
})();
