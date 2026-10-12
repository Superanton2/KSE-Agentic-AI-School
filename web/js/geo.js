// Геолокація. Координати живуть лише в пам'яті сторінки й ідуть тільки в OSRM/Photon — не на наш сервер.
export const KYIV_CENTER = [50.4501, 30.5234];
const KYIV_BBOX = { s: 50.15, n: 50.65, w: 30.15, e: 30.95 }; // межі міста з запасом

export const inKyiv = ([lat, lon]) => lat >= KYIV_BBOX.s && lat <= KYIV_BBOX.n && lon >= KYIV_BBOX.w && lon <= KYIV_BBOX.e;

// → Promise<{latlng, accuracy} | null>; null — відмова, помилка чи таймаут.
export function locate() {
  if (!('geolocation' in navigator)) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ latlng: [p.coords.latitude, p.coords.longitude], accuracy: p.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: false, maximumAge: 60_000, timeout: 8000 },
    );
  });
}
