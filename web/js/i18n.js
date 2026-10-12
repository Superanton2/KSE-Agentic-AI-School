// Усі рядки інтерфейсу — в i18n/<lang>.json. Підстановка {name} — лише як текст.
let dict = {};

export async function loadLang(lang = 'uk') {
  const r = await fetch(`i18n/${lang}.json`);
  dict = await r.json();
  document.documentElement.lang = lang;
}

export function t(key, vars) {
  const s = dict[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k) => String(vars[k] ?? '')) : s;
}

export function applyI18n(root = document) {
  for (const el of root.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of root.querySelectorAll('[data-i18n-aria]')) el.setAttribute('aria-label', t(el.dataset.i18nAria));
}
