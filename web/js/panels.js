// Висувні панелі (налаштування, довідка): одна відкрита за раз, Escape закриває, фокус повертається на кнопку.
const panels = new Map(); // id → { el, btn }
let openId = null;

export function closePanel() {
  if (!openId) return;
  const { el, btn } = panels.get(openId);
  el.hidden = true;
  btn.setAttribute('aria-expanded', 'false');
  openId = null;
  btn.focus({ preventScroll: true });
}

export function openPanel(id) {
  if (openId) closePanel();
  const { el, btn } = panels.get(id);
  el.hidden = false;
  btn.setAttribute('aria-expanded', 'true');
  openId = id;
  el.querySelector('input:not([disabled]), button, a')?.focus({ preventScroll: true });
}

export function registerPanel(id, btnId, onOpen) {
  const el = document.getElementById(id);
  const btn = document.getElementById(btnId);
  btn.setAttribute('aria-controls', id);
  btn.setAttribute('aria-expanded', 'false');
  panels.set(id, { el, btn });
  btn.addEventListener('click', () => {
    if (openId === id) return closePanel();
    onOpen?.();
    openPanel(id);
  });
  el.querySelector('[data-close]')?.addEventListener('click', closePanel);
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && openId) closePanel(); });
