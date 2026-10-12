// Ініціалізація, стан, цикл оновлення.
// Ймовірність — заглушка prob.js (рахує окремий модуль); час дороги — справжній (route.js).
import { getRaions, getState, getStores, isStale } from './api.js';
import { inKyiv, KYIV_CENTER, locate } from './geo.js';
import { applyI18n, loadLang, t } from './i18n.js';
import { createMap } from './map.js';
import { estimate } from './prob.js';
import { cacheKey, createRouter, fallbackTravel, haversineKm } from './route.js';
import { createSearch } from './search.js';
import { renderCard, renderStatus, showBanner } from './ui.js';

const POLL_MS = 15_000;
const POLL_MAX_MS = 120_000;
const SHOP_MIN = 60; // до панелі налаштувань

const app = {
  state: null, lastOkAt: 0,
  stores: [], storeId: null,
  me: null,        // { latlng, accuracy } — лише в пам'яті
  travel: null,    // { key, minutes, approx }
  cardClosed: false, // користувач закрив картку — не відкривати її самим лише кліком по карті
};
const travel = createRouter();

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
  const base = { store: storeView(store), travel: app.travel.minutes, approx: app.travel.approx, shop: SHOP_MIN };
  renderCard(stale ? { ...base, nodata: true } : {
    ...base,
    ...estimate({ state: app.state, store, travelMin: app.travel.minutes, shopMin: SHOP_MIN }),
  }, now);
}

// Опитування /api/state: кожні 15 с; при помилках — тихий повтор із подвоєнням паузи до 2 хв.
async function pollState(delay = POLL_MS) {
  let next = POLL_MS;
  try {
    const prev = app.state;
    app.state = await getState();
    app.lastOkAt = Date.now();
    if (prev?.status === 'calm' && app.state.status === 'alert') showBanner(app.state.level);
  } catch {
    next = Math.min(delay * 2, POLL_MAX_MS);
  }
  render();
  setTimeout(() => pollState(next), next);
}

function setupMenu() {
  const btn = document.getElementById('btn-menu');
  const menu = document.getElementById('menu');
  const toggle = (open) => {
    menu.hidden = !open;
    btn.setAttribute('aria-expanded', String(open));
    if (open) menu.querySelector('a').focus();
  };
  btn.addEventListener('click', (e) => { e.stopPropagation(); toggle(menu.hidden); });
  document.addEventListener('click', (e) => { if (!menu.hidden && !menu.contains(e.target)) toggle(false); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !menu.hidden) { toggle(false); btn.focus(); } });
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

// Перший запит стану — разом із магазинами; далі — цикл pollState.
async function pollFirst() {
  try {
    app.state = await getState();
    app.lastOkAt = Date.now();
  } finally {
    setTimeout(() => pollState(), POLL_MS);
  }
}

async function main() {
  await loadLang('uk');
  applyI18n();

  app.mapView = createMap(document.getElementById('map'));
  const geo = useGeolocation(); // діалог браузера показуємо одразу, паралельно з даними
  const [, stores, raions] = await Promise.allSettled([pollFirst(), getStores(), getRaions()]);
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
  const search = createSearch({
    stores: () => app.stores.map((f) => f.properties),
    storeLabel: (p) => ({ title: storeView(p).name, sub: p.address }),
    onStore: selectStore,
    onPlace: (latlng) => {
      showHint(null);
      setMe(latlng, 0);
      const s = findStore(app.storeId);
      if (s) app.mapView.fitTrip(latlng, [s.lat, s.lon]);
    },
  });
  document.getElementById('btn-search').addEventListener('click', () => (search.isOpen ? search.close() : search.open()));
  setupMenu();

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
