// Розширені налаштування поїздки. Зберігаються в localStorage (у try/catch); координати — ніколи.
const KEY = 'vstyhnu.settings.v1';

// [min, max, step] для кожного числового поля
export const RANGES = {
  shopMean: [20, 120, 5],
  shopSd: [0, 30, 5],
  waitMax: [0, 60, 5],
  openDelay: [0, 30, 5],
  manualTravel: [1, 120, 1],
};
export const DEFAULTS = Object.freeze({ shopMean: 60, shopSd: 15, waitMax: 0, openDelay: 0, manualTravel: null, venue: 'metro' });
const VENUES = ['metro'];

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, Math.round(v)));

// Будь-що (у т.ч. зіпсований localStorage) → коректні налаштування.
export function sanitize(raw) {
  const out = { ...DEFAULTS };
  if (!raw || typeof raw !== 'object') return out;
  for (const k of ['shopMean', 'shopSd', 'waitMax', 'openDelay']) {
    if (Number.isFinite(raw[k])) out[k] = clamp(raw[k], RANGES[k]);
  }
  out.manualTravel = Number.isFinite(raw.manualTravel) ? clamp(raw.manualTravel, RANGES.manualTravel) : null;
  if (VENUES.includes(raw.venue)) out.venue = raw.venue;
  return out;
}

export function loadSettings(storage = globalThis.localStorage) {
  try {
    return sanitize(JSON.parse(storage.getItem(KEY)));
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveSettings(s, storage = globalThis.localStorage) {
  try {
    storage.setItem(KEY, JSON.stringify(sanitize(s)));
  } catch { /* приватний режим / заблоковане сховище — працюємо без збереження */ }
}

// Прив'язка форми панелі ⚙. fmt(key, value) → підпис значення; onChange(nextSettings);
// suggestTravel() — поточний час маршруту, ним заповнюємо ручне поле при ввімкненні.
export function bindSettingsForm(initial, { fmt, onChange, suggestTravel = () => null }) {
  let s = sanitize(initial);
  const $ = (id) => document.getElementById(id);
  const manual = $('s-manual');
  const keys = ['shopMean', 'shopSd', 'waitMax', 'openDelay', 'manualTravel'];

  function draw() {
    for (const k of keys) {
      const input = $(`s-${k}`);
      const [min, max, step] = RANGES[k];
      Object.assign(input, { min, max, step });
      const v = k === 'manualTravel' ? (s.manualTravel ?? input.valueAsNumber ?? 20) : s[k];
      input.value = String(v);
      $(`s-${k}-out`).textContent = fmt(k, k === 'manualTravel' ? s.manualTravel : v);
    }
    manual.checked = s.manualTravel !== null;
    $('s-manualTravel').disabled = !manual.checked;
  }

  function set(patch) {
    s = sanitize({ ...s, ...patch });
    saveSettings(s);
    draw();
    onChange(s);
  }

  for (const k of keys) $(`s-${k}`).addEventListener('input', (e) => set({ [k]: e.target.valueAsNumber }));
  manual.addEventListener('change', () => set({ manualTravel: manual.checked ? (suggestTravel() ?? $('s-manualTravel').valueAsNumber) : null }));
  $('s-reset').addEventListener('click', () => set({ ...DEFAULTS }));
  $('s-manualTravel').value = '20';
  draw();
  return { get: () => s };
}
