// Час дороги: OSRM (FOSSGIS) прямо з браузера; якщо не відповів за 4 с — оцінка по прямій.
// Затори не враховано (про це — рядок у картці).
const OSRM = 'https://routing.openstreetmap.de/routed-car/route/v1/driving';
const TIMEOUT_MS = 4000;
const MIN_INTERVAL_MS = 5000;
const DETOUR = 1.4;       // дорога довша за пряму
const FALLBACK_KMH = 25;  // середня швидкість містом

export function haversineKm([lat1, lon1], [lat2, lon2]) {
  const rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

export const fallbackTravel = (a, b) => ({ minutes: (haversineKm(a, b) * DETOUR / FALLBACK_KMH) * 60, approx: true });

// Старт округлюємо до ~200 м: 0.002° широти ≈ 220 м, 0.003° довготи на широті Києва ≈ 210 м.
export const cacheKey = ([lat, lon], storeId) => `${Math.round(lat / 0.002)}:${Math.round(lon / 0.003)}:${storeId}`;

export function osrmUrl([lat, lon], store) {
  return `${OSRM}/${lon.toFixed(5)},${lat.toFixed(5)};${store.lon.toFixed(5)},${store.lat.toFixed(5)}?overview=false`;
}

async function queryOsrm(fetchImpl, start, store) {
  try {
    const r = await fetchImpl(osrmUrl(start, store), {
      signal: AbortSignal.timeout(TIMEOUT_MS), credentials: 'omit', referrerPolicy: 'no-referrer',
    });
    if (!r.ok) throw new Error(`OSRM HTTP ${r.status}`);
    const j = await r.json();
    const route = j.code === 'Ok' && j.routes?.[0];
    if (!route) throw new Error(`OSRM ${j.code}`);
    return { minutes: route.duration / 60, km: route.distance / 1000, approx: false };
  } catch {
    return fallbackTravel(start, [store.lat, store.lon]);
  }
}

// travel(start, store) → Promise<{minutes, approx} | null>.
// Кеш у пам'яті; у мережу — не частіше ніж раз на minInterval, проміжні виклики витісняються
// останнім (витіснений проміс отримує null). Невдалий запит (fallback) не кешується.
export function createRouter({ fetchImpl = (...a) => fetch(...a), now = Date.now, minInterval = MIN_INTERVAL_MS } = {}) {
  const cache = new Map();
  let lastAt = -Infinity, timer = null, pending = null;

  return function travel(start, store) {
    const key = cacheKey(start, store.id);
    if (cache.has(key)) return cache.get(key);
    pending?.resolve(null);
    clearTimeout(timer);
    return new Promise((resolve) => {
      pending = { resolve };
      timer = setTimeout(() => {
        const mine = pending;
        pending = null;
        lastAt = now();
        const p = queryOsrm(fetchImpl, start, store);
        cache.set(key, p);
        p.then((r) => { if (r.approx) cache.delete(key); mine.resolve(r); });
      }, Math.max(0, lastAt + minInterval - now()));
    });
  };
}
