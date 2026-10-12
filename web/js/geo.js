// Геолокація — як у картах: за замовчуванням старт = «моя локація», оновлюється, поки сторінка відкрита.
// Координати живуть лише в пам'яті сторінки й ідуть тільки в OSRM — не на наш сервер.
export const KYIV_CENTER = [50.4501, 30.5234];
const KYIV_BBOX = { s: 50.15, n: 50.65, w: 30.15, e: 30.95 }; // межі міста з запасом
// Ноутбук (Wi-Fi/IP) часом шукає першу позицію довше 8 с.
const OPTS = { enableHighAccuracy: false, maximumAge: 60_000, timeout: 15_000 };

export const inKyiv = ([lat, lon]) => lat >= KYIV_BBOX.s && lat <= KYIV_BBOX.n && lon >= KYIV_BBOX.w && lon <= KYIV_BBOX.e;

// Причина, чому локації немає:
//   insecure    — сторінка не на https/localhost, браузер геолокацію не дає взагалі;
//   unsupported — у браузері немає Geolocation API;
//   denied      — користувач заборонив геолокацію цьому сайту;
//   unavailable — браузер не отримав позицію (на macOS — зазвичай служби геолокації вимкнені для браузера);
//   timeout     — позиції ще немає, але спостереження триває.
export function geoProblem(err) {
  if (!window.isSecureContext) return 'insecure';
  if (!('geolocation' in navigator)) return 'unsupported';
  return { 1: 'denied', 2: 'unavailable', 3: 'timeout' }[err?.code] ?? 'unavailable';
}

// onPos({latlng, accuracy}) на кожне оновлення; onError(reason) — поки позиції ще не було (або відмова).
// Повертає stop().
export function watchLocation(onPos, onError) {
  if (!window.isSecureContext || !('geolocation' in navigator)) {
    onError(geoProblem());
    return () => {};
  }
  let got = false;
  const id = navigator.geolocation.watchPosition(
    (p) => { got = true; onPos({ latlng: [p.coords.latitude, p.coords.longitude], accuracy: p.coords.accuracy }); },
    (e) => {
      console.info(`geolocation error ${e.code}: ${e.message}`); // для діагностики: 1 — заборона, 2 — недоступно, 3 — таймаут
      if (e.code === 1) navigator.geolocation.clearWatch(id); // відмова — більше не питаємо
      if (!got || e.code === 1) onError(geoProblem(e));
    },
    OPTS,
  );
  return () => navigator.geolocation.clearWatch(id);
}
