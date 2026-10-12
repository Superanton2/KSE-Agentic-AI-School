// Ініціалізація, стан, цикл оновлення.
// Ймовірності в картці поки фейкові (DEMO) — sim.js на наступному кроці; час дороги — справжній (route.js).
import { getRaions, getState, getStores, isStale, mockVariant } from './api.js';
import { inKyiv, KYIV_CENTER, locate } from './geo.js';
import { applyI18n, loadLang, t } from './i18n.js';
import { createMap } from './map.js';
import { cacheKey, createRouter, fallbackTravel, haversineKm } from './route.js';
import { renderCard, renderStatus } from './ui.js';

const app = {
  state: null, lastOkAt: 0,
  stores: [], storeId: null,
  me: null,        // { latlng, accuracy } — лише в пам'яті
  travel: null,    // { key, minutes, approx }
  cardClosed: false, // користувач закрив картку — не відкривати її самим лише кліком по карті
};
const travel = createRouter();

// ── Фейкові ймовірності для макета ────────────────────────────
const curveFrom = (ps) => ps.map((p, i) => ({ depart_in: i * 5, p }));
const DEMO = {
  calm: { p: 0.74, band: [0.66, 0.81], curve: curveFrom([0.74, 0.76, 0.79, 0.81, 0.8, 0.77, 0.72, 0.66, 0.61, 0.58, 0.55, 0.52, 0.5]) },
  alert: { p: 0.41, band: [0.3, 0.52], wait: { median: 25, p80: 50 }, curve: curveFrom([0.41, 0.46, 0.52, 0.57, 0.61, 0.63, 0.62, 0.6, 0.57, 0.55, 0.52, 0.5, 0.47]) },
  'alert-red': { p: 0.28, band: [0.19, 0.4], wait: { median: 34, p80: 58 }, curve: curveFrom([0.28, 0.3, 0.33, 0.37, 0.42, 0.46, 0.49, 0.52, 0.54, 0.53, 0.51, 0.49, 0.46]) },
  stale: { nodata: true },
};
function demoResult(store) {
  const d = DEMO[mockVariant] ?? DEMO.calm;
  const best = d.curve ? d.curve.reduce((a, b) => (b.p > a.p ? b : a)) : null;
  return { store, shop: 60, ...d, best };
}

// ──────────────────────────────────────────────────────────────
const findStore = (id) => app.stores.find((s) => s.properties.id === id)?.properties;
const storeView = (p) => ({ ...p, name: /^metro( київ)?$/i.test(p.name) ? 'Metro' : p.name });

function nearestStore(latlng) {
  let best = null, bestKm = Infinity;
  for (const { properties: p } of app.stores) {
    const km = haversineKm(latlng, [p.lat, p.lon]);
    if (km < bestKm) { best = p; bestKm = km; }
  }
  return best;
}

let hintTimer = null;
function showHint(key, ms = 0) {
  const el = document.getElementById('hint');
  clearTimeout(hintTimer);
  el.textContent = key ? t(key) : '';
  el.hidden = !key;
  if (key && ms) hintTimer = setTimeout(() => { el.hidden = true; }, ms);
}

// Одразу — оцінка по прямій («приблизно»), потім уточнення з OSRM, якщо старт/магазин не змінились.
function updateTravel() {
  const store = findStore(app.storeId);
  if (!store || !app.me) { app.travel = null; return; }
  const start = app.me.latlng;
  const key = cacheKey(start, store.id);
  if (app.travel?.key === key && !app.travel.approx) return;
  app.travel = { key, ...fallbackTravel(start, [store.lat, store.lon]) };
  travel(start, store).then((r) => {
    if (!r || cacheKey(app.me.latlng, app.storeId) !== key) return; // витіснено новішим запитом
    app.travel = { key, ...r };
    render();
  });
}

function setMe(latlng, accuracy) {
  app.me = { latlng, accuracy };
  app.mapView.setMe(latlng, accuracy);
  if (!inKyiv(latlng)) showHint('geo.outside', 8000);
  if (!app.storeId && !app.cardClosed) {
    const s = nearestStore(latlng);
    if (s) return selectStore(s.id);
  }
  updateTravel();
  render();
}

function selectStore(id) {
  const store = findStore(id);
  if (!store) return;
  app.storeId = id;
  app.cardClosed = false;
  app.mapView.selectStore(id);
  if (app.me) app.mapView.fitTrip(app.me.latlng, [store.lat, store.lon]);
  updateTravel();
  render();
}

function render() {
  const now = Date.now();
  const stale = isStale(app.state, app.lastOkAt, now);
  if (app.state) renderStatus(app.state, stale, now);
  const store = findStore(app.storeId);
  if (!store || !app.travel) return renderCard(null);
  renderCard({
    ...demoResult(storeView(store)),
    travel: app.travel.minutes,
    approx: app.travel.approx,
    ...(stale ? { nodata: true } : {}),
  }, now);
}

async function useGeolocation() {
  const pos = await locate();
  if (pos) {
    showHint(null);
    setMe(pos.latlng, pos.accuracy);
  } else {
    if (!app.me) setMe(KYIV_CENTER, 0);
    showHint('geo.hint');
  }
}

async function main() {
  await loadLang('uk');
  applyI18n();

  app.mapView = createMap(document.getElementById('map'));
  const geo = useGeolocation(); // діалог браузера показуємо одразу, паралельно з даними
  const [state, stores, raions] = await Promise.allSettled([getState(), getStores(), getRaions()]);
  if (state.status === 'fulfilled') { app.state = state.value; app.lastOkAt = Date.now(); }
  if (raions.status === 'fulfilled') app.mapView.setRaions(raions.value);
  if (stores.status === 'fulfilled') {
    app.stores = stores.value.features;
    app.mapView.setStores(stores.value, selectStore, (p) => t('store.label', storeView(p)));
  }
  if (app.me && !app.storeId) setMe(app.me.latlng, app.me.accuracy); // геолокація встигла раніше за магазини

  app.mapView.onPick((latlng) => { showHint(null); setMe(latlng, 0); });
  document.getElementById('btn-locate').addEventListener('click', async () => {
    await useGeolocation();
    const s = findStore(app.storeId);
    if (s && app.me) app.mapView.fitTrip(app.me.latlng, [s.lat, s.lon]);
  });
  document.getElementById('card-close').addEventListener('click', () => {
    app.storeId = null;
    app.cardClosed = true;
    app.mapView.selectStore(null);
    render();
  });

  await geo;
  render();
  setInterval(render, 1000); // таймер статусу тікає локально
}

main();
