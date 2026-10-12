// Мережа: fetch з таймаутом і застарілість даних.
// Перехід на справжній бекенд — заміна API_BASE на '/api' (той самий origin, без CORS).
export const API_BASE = 'mock';

export const STALE_MS = 10 * 60_000;
const TIMEOUT_MS = 5000;

const mockVariant = new URLSearchParams(location.search).get('mock') || 'calm';

export async function getJSON(url, { timeout = TIMEOUT_MS } = {}) {
  const r = await fetch(url, { signal: AbortSignal.timeout(timeout), cache: 'no-store' });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

// У mock-файлах часи записані відносно поля `now`; зсуваємо їх на поточний момент,
// щоб таймер і застарілість поводились як наживо.
const ISO = /^\d{4}-\d\d-\d\dT\d\d:\d\d(:\d\d)?(\.\d+)?Z$/;
function shiftTimes(v, delta) {
  if (typeof v === 'string' && ISO.test(v)) return new Date(Date.parse(v) + delta).toISOString();
  if (Array.isArray(v)) return v.map((x) => shiftTimes(x, delta));
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, shiftTimes(x, delta)]));
  return v;
}

// Варіант може бути послідовністю: n-й запит отримує n-й елемент (останній — далі), напр. flip: спокій → тривога.
const mockCalls = {};
async function getMock(name) {
  const m = await getJSON(`mock/${name}.json`);
  let v = m.variants ? (m.variants[mockVariant] ?? m.variants.calm) : m.data;
  if (Array.isArray(v)) {
    const n = (mockCalls[name] = (mockCalls[name] ?? -1) + 1);
    v = m.variants[v[Math.min(n, v.length - 1)]];
  }
  return shiftTimes(v, Date.now() - Date.parse(m.now));
}

export const getState = () => (API_BASE === 'mock' ? getMock('state') : getJSON(`${API_BASE}/state`));
export const getModelCard = () => (API_BASE === 'mock' ? getMock('model-card') : getJSON(`${API_BASE}/model-card`));
export const getStores = () => getJSON('data/stores.geojson');
export const getRaions = () => getJSON('data/kyiv_raions.geojson');

// Дані вважаються застарілими, якщо джерело давно не оновлювалось або API давно не відповідав.
export function isStale(state, lastOkAt, now = Date.now()) {
  if (!state) return true;
  return now - Date.parse(state.data_as_of) > STALE_MS || now - lastOkAt > STALE_MS;
}
