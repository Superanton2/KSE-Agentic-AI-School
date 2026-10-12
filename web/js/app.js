// Ініціалізація, стан, цикл оновлення.
// Крок 1 (макет): картка заповнюється фейковим результатом DEMO; sim.js / route.js / geo.js — на наступних кроках.
import { getRaions, getState, getStores, isStale, mockVariant } from './api.js';
import { applyI18n, loadLang, t } from './i18n.js';
import { createMap } from './map.js';
import { renderCard, renderStatus } from './ui.js';

const KYIV_CENTER = [50.4501, 30.5234];

const app = { state: null, lastOkAt: 0, stores: [], storeId: null, me: { latlng: [50.4392, 30.5169], accuracy: 350 } };

// ── Фейковий результат для макета ─────────────────────────────
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
  return { store, travel: 18, approx: false, shop: 60, ...d, best };
}

// ──────────────────────────────────────────────────────────────
function storeView(f) {
  const p = f.properties;
  return { ...p, name: /^metro$/i.test(p.name) ? 'Metro' : p.name };
}

function selectStore(id) {
  const f = app.stores.find((s) => s.properties.id === id);
  if (!f) return;
  app.storeId = id;
  app.mapView.selectStore(id);
  app.mapView.fitTrip(app.me.latlng, [f.properties.lat, f.properties.lon]);
  render();
}

function render() {
  const now = Date.now();
  const stale = isStale(app.state, app.lastOkAt, now);
  if (app.state) renderStatus(app.state, stale, now);
  const f = app.stores.find((s) => s.properties.id === app.storeId);
  renderCard(f ? { ...demoResult(storeView(f)), ...(stale ? { nodata: true } : {}) } : null, now);
}

async function main() {
  await loadLang('uk');
  applyI18n();

  app.mapView = createMap(document.getElementById('map'));
  const [state, stores, raions] = await Promise.allSettled([getState(), getStores(), getRaions()]);
  if (state.status === 'fulfilled') { app.state = state.value; app.lastOkAt = Date.now(); }
  if (raions.status === 'fulfilled') app.mapView.setRaions(raions.value);
  if (stores.status === 'fulfilled') {
    app.stores = stores.value.features;
    app.mapView.setStores(stores.value, selectStore, (p) => t('store.label', storeView({ properties: p })));
  }
  app.mapView.setMe(app.me.latlng ?? KYIV_CENTER, app.me.accuracy);

  document.getElementById('card-close').addEventListener('click', () => {
    app.storeId = null;
    app.mapView.selectStore(null);
    render();
  });

  // Макет: одразу показуємо картку для першого магазину (у ТЗ — «Теремки»/Кільцева).
  const demo = app.stores.find((s) => /Кільцева/.test(s.properties.address)) ?? app.stores[0];
  if (demo) selectStore(demo.properties.id);
  render();
  setInterval(render, 1000); // таймер статусу тікає локально
}

main();
