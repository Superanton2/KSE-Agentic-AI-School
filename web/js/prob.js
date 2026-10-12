// Ймовірність: готові числа з бекенду (GET /api/estimate). Бекенд отримує лише хвилини, без координат.
// render() синхронний, тож estimate() повертає останню відповідь з кешу, а новий запит іде у фоні
// й після відповіді викликає onUpdate (перемальовка). Режим 'mock' — фіксовані числа для макета.
// Вихід: { p, band:[lo,hi], wait?:{median,p80}, curve:[{depart_in,p}], best, unsure? } | { nodata } | null
import { API_BASE, getJSON } from './api.js';

const REFRESH_MS = 30_000; // сценарії на бекенді оновлюються раз на 30 с
const curveFrom = (ps) => ps.map((p, i) => ({ depart_in: i * 5, p }));

const STUB = {
  calm: { p: 0.74, band: [0.66, 0.81], curve: curveFrom([0.74, 0.76, 0.79, 0.81, 0.8, 0.77, 0.72, 0.66, 0.61, 0.58, 0.55, 0.52, 0.5]) },
  yellow: { p: 0.41, band: [0.3, 0.52], wait: { median: 25, p80: 50 }, curve: curveFrom([0.41, 0.46, 0.52, 0.57, 0.61, 0.63, 0.62, 0.6, 0.57, 0.55, 0.52, 0.5, 0.47]) },
  red: { p: 0.28, band: [0.19, 0.4], wait: { median: 34, p80: 58 }, curve: curveFrom([0.28, 0.3, 0.33, 0.37, 0.42, 0.46, 0.49, 0.52, 0.54, 0.53, 0.51, 0.49, 0.46]) },
};

function stub(state) {
  const s = state?.status === 'alert' ? STUB[state.level === 'red' ? 'red' : 'yellow'] : STUB.calm;
  return { ...s, best: s.curve.reduce((a, b) => (b.p > a.p ? b : a)) };
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, Math.round(v)));

export function query(travelMin, settings) {
  return new URLSearchParams({
    travel: clamp(travelMin, 0, 180),
    depart_in: 0,
    shop_mean: clamp(settings.shopMean, 20, 120),
    shop_sd: clamp(settings.shopSd, 0, 60),
    wait_max: clamp(settings.waitMax, 0, 60),
    open_delay: clamp(settings.openDelay, 0, 30),
  }).toString();
}

// Відповідь бекенду → формат картки. p == null (немає сценаріїв) — «немає даних».
export function fromApi(r) {
  if (!r || typeof r.p !== 'number' || !Array.isArray(r.band)) return { nodata: true };
  const curve = Array.isArray(r.curve) ? r.curve.filter((c) => typeof c.p === 'number') : [];
  const ok = curve.length > 0 && r.best && typeof r.best.p === 'number';
  return {
    p: r.p, band: r.band, wait: r.wait ?? null,
    curve: ok ? curve : null, best: ok ? r.best : null,
  };
}

const cache = { key: null, at: 0, value: null, pending: null };

export function estimate({ state, travelMin, settings }, onUpdate = () => {}, now = Date.now()) {
  if (API_BASE === 'mock') return stub(state);
  const key = `${query(travelMin, settings)}|${state?.status}|${state?.level}`;
  const fresh = cache.key === key && now - cache.at < REFRESH_MS;
  if (!fresh && cache.pending !== key) {
    cache.pending = key;
    getJSON(`${API_BASE}/estimate?${query(travelMin, settings)}`)
      .then(fromApi, () => ({ nodata: true }))
      .then((value) => {
        if (cache.pending !== key) return; // за цей час параметри змінились
        Object.assign(cache, { key, at: Date.now(), value, pending: null });
        onUpdate();
      });
  }
  // Поки йде перший запит з новими параметрами — старе число не показуємо.
  return cache.key === key ? cache.value : null;
}
