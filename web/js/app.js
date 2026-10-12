// Ініціалізація, стан, цикл оновлення.
// Ймовірність — з бекенду (prob.js → /api/estimate); час дороги — у браузері (route.js).
// Старт поїздки — як у картах: «моя локація» за замовчуванням, інша адреса — через пошук.
import { getModelCard, getRaions, getState, getStores, isStale } from './api.js';
import { inKyiv, KYIV_CENTER, watchLocation } from './geo.js';
import { applyI18n, loadLang, t } from './i18n.js';
import { createMap } from './map.js';
import { closePanel, registerPanel } from './panels.js';
import { estimate } from './prob.js';
import { cacheKey, createRouter, fallbackTravel, haversineKm } from './route.js';
import { createSearch } from './search.js';
import { bindSettingsForm, loadSettings } from './settings.js';
import { renderCard, renderStatus, showBanner } from './ui.js';
import { unsureReason } from './unsure.js';

const POLL_MS = 15_000;
const POLL_MAX_MS = 120_000;
const MOVE_KM = 0.15; // зсув «моєї локації», після якого перераховуємо дорогу

const app = {
  state: null, lastOkAt: 0,
  stores: [], storeId: null,
  me: null,          // { latlng, accuracy } — геолокація, лише в пам'яті
  from: null,        // { latlng, label } — старт з пошуку; null = «моя локація»
  geoProblem: null,  // 'denied' | 'insecure' | 'unsupported' | 'unavailable'
  travel: null,      // { key, minutes, approx }
  cardClosed: false, // користувач закрив картку — не відкривати її знову автоматично
  settings: loadSettings(),
  modelCard: null,   // skill по горизонтах — для «Дуже неточно»
};
const travel = createRouter();
let search = null;
let stopWatch = () => {};

// ──────────────────────────────────────────────────────────────
const findStore = (id) => app.stores.find((s) => s.properties.id === id)?.properties;
const storeView = (p) => ({ ...p, name: /^metro( київ)?$/i.test(p.name) ? 'Metro' : p.name });
// Геолокація поза Києвом (на ноутбуці буває хибна — Wi-Fi/IP) стартом не вважається.
const meUsable = () => !!app.me && inKyiv(app.me.latlng);
const startLatLng = () => app.from?.latlng ?? (meUsable() ? app.me.latlng : null);

function nearestStore(latlng) {
  let best = null, bestKm = Infinity;
  for (const { properties: p } of app.stores) {
    const km = haversineKm(latlng, [p.lat, p.lon]);
    if (km < bestKm) { best = p; bestKm = km; }
  }
  return best;
}

// Підказка під статусом; з action — це кнопка (напр. «вкажіть, звідки їдете» → пошук).
let hintTimer = null, hintAction = null;
function showHint(key, { ms = 0, action = null, vars } = {}) {
  const el = document.getElementById('hint');
  clearTimeout(hintTimer);
  el.textContent = key ? t(key, vars) : '';
  el.hidden = !key;
  hintAction = action;
  el.classList.toggle('is-action', !!action);
  if (key && ms) hintTimer = setTimeout(() => { el.hidden = true; }, ms);
}

// Одразу — оцінка по прямій («приблизно»), потім уточнення з OSRM, якщо старт/магазин не змінились.
function updateTravel() {
  const store = findStore(app.storeId);
  const start = startLatLng();
  if (!store || !start) { app.travel = null; return; }
  const key = cacheKey(start, store.id);
  if (app.travel?.key === key) return;
  app.travel = { key, ...fallbackTravel(start, [store.lat, store.lon]) };
  travel(start, store).then((r) => {
    const now = startLatLng();
    if (!r || !now || cacheKey(now, app.storeId) !== key) return; // витіснено новішим запитом
    app.travel = { key, ...r };
    render();
  });
}

// Старт змінився: обрати найближчий магазин (якщо ще не обрано) і показати обидві точки.
function onStartChanged({ fit = true } = {}) {
  const start = startLatLng();
  if (!start) return render();
  if (!app.storeId && !app.cardClosed) {
    const s = nearestStore(start);
    if (s) return selectStore(s.id);
  }
  const s = findStore(app.storeId);
  if (fit && s) app.mapView.fitTrip(start, [s.lat, s.lon]);
  updateTravel();
  render();
}

function onLocation(pos) {
  const first = !app.me;
  const moved = first || haversineKm(app.me.latlng, pos.latlng) > MOVE_KM;
  app.me = pos;
  app.geoProblem = null;
  app.mapView.setMe(pos.latlng, pos.accuracy);
  if (!app.from) showFarHint();
  if (app.from) return; // їдемо з адреси з пошуку — синя точка оновлюється, маршрут ні
  if (moved) onStartChanged({ fit: first });
}

// Поза Києвом — кажемо, наскільки далеко, і пропонуємо вказати адресу; у Києві — прибираємо підказку.
function showFarHint() {
  if (meUsable()) return showHint(null);
  const km = Math.round(haversineKm(app.me.latlng, KYIV_CENTER));
  showHint('geo.far', { vars: { km }, action: () => search.open() });
}

function onLocationError(reason) {
  app.geoProblem = reason;
  if (!app.me && !app.from) showHint(`geo.${reason}`, { action: () => search.open() });
  render();
}

function startWatching() {
  stopWatch();
  stopWatch = watchLocation(onLocation, onLocationError);
}

function setFrom(latlng, label) {
  app.from = { latlng, label };
  app.mapView.setStart(latlng);
  showHint(null);
  onStartChanged();
}

function useMyLocation() {
  app.from = null;
  app.mapView.setStart(null);
  if (app.me) {
    showFarHint();
    onStartChanged();
    if (!app.storeId && meUsable()) app.mapView.panTo(app.me.latlng);
  } else {
    startWatching(); // після відмови браузер може спитати ще раз, якщо користувач змінив дозвіл
  }
}

function selectStore(id) {
  const store = findStore(id);
  if (!store) return;
  app.storeId = id;
  app.cardClosed = false;
  app.mapView.selectStore(id);
  const start = startLatLng();
  if (start) app.mapView.fitTrip(start, [store.lat, store.lon]);
  updateTravel();
  render();
}

function render() {
  const now = Date.now();
  const stale = isStale(app.state, app.lastOkAt, now);
  if (app.state) renderStatus(app.state, stale, now);
  const store = findStore(app.storeId);
  if (!store) return renderCard(null);
  const set = app.settings;
  const manual = set.manualTravel !== null;
  const from = app.from ? { label: app.from.label } : meUsable() ? { me: true } : null;
  if (!from && !manual) return renderCard({ store: storeView(store), nostart: true }, now);
  const travelMin = manual ? set.manualTravel : app.travel?.minutes;
  if (travelMin == null) return renderCard(null);
  const base = { store: storeView(store), from, travel: travelMin, approx: !manual && app.travel.approx, manual, shop: set.shopMean };
  if (stale) return renderCard({ ...base, nodata: true }, now);

  const r = estimate({ state: app.state, travelMin, settings: set }, render);
  if (!r) return; // відповідь бекенду ще в дорозі — картку не чіпаємо, render() викличеться знову
  if (r.nodata) return renderCard({ ...base, nodata: true }, now);
  const reason = unsureReason({
    travel: travelMin, wait: r.wait ? Math.min(r.wait.median, set.waitMax) : 0, openDelay: set.openDelay,
    shop: set.shopMean, band: r.band, skill: app.modelCard?.skill,
  });
  renderCard({ ...base, ...r, unsure: reason !== null, unsureReason: reason }, now);
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

// Перший запит стану — разом із магазинами; далі — цикл pollState.
async function pollFirst() {
  try {
    app.state = await getState();
    app.lastOkAt = Date.now();
  } finally {
    setTimeout(() => pollState(), POLL_MS);
  }
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

// Кнопки й панелі — одразу, ще до завантаження даних, щоб інтерфейс не був «мертвим».
function setupUi() {
  search = createSearch({
    stores: () => app.stores.map((f) => f.properties),
    storeLabel: (p) => ({ title: storeView(p).name, sub: p.address }),
    myLocation: () => (app.from || !meUsable()
      ? { title: t('search.my_location'), sub: t(meUsable() ? 'search.my_location.sub' : app.me ? 'search.my_location.far' : 'search.my_location.ask') }
      : null),
    onMe: useMyLocation,
    onStore: selectStore,
    onPlace: setFrom,
  });
  document.getElementById('btn-search').addEventListener('click', () => {
    if (search.isOpen) return search.close();
    closePanel();
    search.open();
  });
  setupMenu();

  // ⚙ і ⓘ: висувні панелі; відкриття однієї закриває пошук та іншу.
  const closeSearch = () => search.isOpen && search.close();
  registerPanel('settings', 'btn-settings', closeSearch);
  registerPanel('info', 'btn-info', closeSearch);
  bindSettingsForm(app.settings, {
    fmt: (k, v) => {
      if (k === 'manualTravel') return v === null ? t('settings.off') : t('dur.min', { m: v });
      if (k === 'shopSd') return `±${t('dur.min', { m: v })}`;
      if (k === 'waitMax' && v === 0) return t('settings.noWait');
      return t('dur.min', { m: v });
    },
    suggestTravel: () => (app.travel ? Math.round(app.travel.minutes) : null),
    onChange: (s) => { app.settings = s; render(); },
  });

  document.getElementById('btn-locate').addEventListener('click', useMyLocation);
  document.getElementById('hint').addEventListener('click', () => {
    if (hintAction) hintAction();
    else showHint(null);
  });
  document.getElementById('card-cta').addEventListener('click', () => { closePanel(); search.open(); });
  document.getElementById('card-close').addEventListener('click', () => {
    app.storeId = null;
    app.cardClosed = true;
    app.mapView.selectStore(null);
    render();
  });
}

async function main() {
  await loadLang('uk');
  applyI18n();
  app.mapView = createMap(document.getElementById('map'));
  setupUi();
  startWatching(); // діалог браузера — одразу, паралельно з даними

  const [, stores, raions, card] = await Promise.allSettled([pollFirst(), getStores(), getRaions(), getModelCard()]);
  if (card.status === 'fulfilled') app.modelCard = card.value;
  if (raions.status === 'fulfilled') app.mapView.setRaions(raions.value);
  if (stores.status === 'fulfilled') {
    app.stores = stores.value.features;
    app.mapView.setStores(stores.value, selectStore, (p) => t('store.label', storeView(p)));
  }
  if (startLatLng()) onStartChanged(); // геолокація встигла раніше за магазини
  render();
  setInterval(render, 1000); // таймер статусу тікає локально
}

main();
