// Пошук: спершу магазини (локально), потім адреси через Photon. Обрана адреса — точка відправлення.
// Відповіді Photon і назви з OSM — недовірені: лише textContent.
import { t } from './i18n.js';

const PHOTON = 'https://photon.komoot.io/api/';
const KYIV_BBOX = '30.23,50.21,30.83,50.59'; // lon_min,lat_min,lon_max,lat_max
const DEBOUNCE_MS = 400;
const MIN_CHARS = 3;
const TIMEOUT_MS = 8000; // Photon часом відповідає 5+ с

export const normalize = (s) => (s ?? '').toLocaleLowerCase('uk').replace(/[’ʼ`]/g, "'").replace(/\s+/g, ' ').trim();

// Усі слова запиту мають знайтись у «назва + адреса».
export function matchStores(stores, q) {
  const words = normalize(q).split(' ').filter(Boolean);
  if (!words.length) return [];
  return stores.filter((p) => {
    const hay = normalize(`${p.name} ${p.address}`);
    return words.every((w) => hay.includes(w));
  });
}

// Тип об'єкта — щоб розрізняти однойменні результати (вулиця / станція / вхід у метро).
const KIND = {
  'railway:station': 'kind.station', 'railway:stop': 'kind.stop', 'railway:subway_entrance': 'kind.subway_entrance',
  'railway:halt': 'kind.stop', 'highway:bus_stop': 'kind.stop', 'place:neighbourhood': 'kind.area',
  'place:suburb': 'kind.area', 'place:quarter': 'kind.area', 'waterway:stream': 'kind.water', 'waterway:river': 'kind.water',
};
const kindOf = (p) => {
  const k = KIND[`${p.osm_key}:${p.osm_value}`] ?? (p.osm_key === 'highway' ? 'kind.street' : p.osm_key === 'building' ? 'kind.building' : null);
  return k ? t(k) : '';
};

export function photonItem(f) {
  const p = f.properties ?? {};
  const street = [p.street, p.housenumber].filter(Boolean).join(', ');
  const title = p.name || street || p.district || p.city;
  const sub = [kindOf(p), p.name ? street : '', p.district, p.city].filter((x) => x && x !== title).join(' · ');
  const [lon, lat] = f.geometry?.coordinates ?? [];
  return title && Number.isFinite(lat) && Number.isFinite(lon) ? { title, sub, latlng: [lat, lon] } : null;
}

export function photonUrl(q) {
  return `${PHOTON}?${new URLSearchParams({ q, bbox: KYIV_BBOX, limit: '6' })}`;
}

async function searchPhoton(q, signal) {
  const r = await fetch(photonUrl(q), { signal, credentials: 'omit', referrerPolicy: 'no-referrer' });
  if (!r.ok) throw new Error(`Photon HTTP ${r.status}`);
  const seen = new Set();
  return (await r.json()).features.map(photonItem).filter((it) => {
    const key = it && `${it.title}|${it.sub}`;
    if (!it || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// stores(): масив properties магазинів; onStore(id); onPlace(latlng).
export function createSearch({ stores, storeLabel, onStore, onPlace }) {
  const panel = document.getElementById('search');
  const input = document.getElementById('search-input');
  const list = document.getElementById('search-list');
  const status = document.getElementById('search-status');
  let items = [], active = -1, timer = null, ctrl = null;

  function setStatus(key) { status.textContent = key ? t(key) : ''; }

  function draw() {
    list.replaceChildren(...items.map((it, i) => {
      const li = document.createElement('li');
      li.id = `search-opt-${i}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', String(i === active));
      li.className = `opt opt-${it.kind}`;
      const title = document.createElement('span');
      title.className = 'opt-title';
      title.textContent = it.title;
      const sub = document.createElement('span');
      sub.className = 'opt-sub';
      sub.textContent = it.sub;
      li.append(title, sub);
      li.addEventListener('pointerdown', (e) => e.preventDefault()); // не втрачати фокус до click
      li.addEventListener('click', () => pick(i));
      return li;
    }));
    input.setAttribute('aria-expanded', String(items.length > 0));
    if (active >= 0) input.setAttribute('aria-activedescendant', `search-opt-${active}`);
    else input.removeAttribute('aria-activedescendant');
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  }

  function pick(i) {
    const it = items[i];
    if (!it) return;
    close();
    if (it.kind === 'store') onStore(it.id);
    else onPlace(it.latlng);
  }

  function update() {
    const q = input.value;
    const local = matchStores(stores(), q).map((p) => ({ kind: 'store', id: p.id, ...storeLabel(p) }));
    items = local;
    active = items.length ? 0 : -1;
    draw();
    clearTimeout(timer);
    ctrl?.abort();
    if (normalize(q).length < MIN_CHARS) return setStatus(q.trim() && !local.length ? 'search.min_chars' : null);
    setStatus('search.loading');
    timer = setTimeout(async () => {
      ctrl = new AbortController();
      const signal = AbortSignal.any([ctrl.signal, AbortSignal.timeout(TIMEOUT_MS)]);
      try {
        const places = (await searchPhoton(q, signal)).map((p) => ({ kind: 'place', ...p }));
        if (input.value !== q) return;
        items = [...local, ...places];
        if (active < 0 && items.length) active = 0;
        draw();
        setStatus(items.length ? null : 'search.empty');
      } catch (e) {
        if (e.name !== 'AbortError' || input.value === q) setStatus(local.length ? null : 'search.error');
      }
    }, DEBOUNCE_MS);
  }

  function open() {
    panel.hidden = false;
    input.value = '';
    items = [];
    active = -1;
    draw();
    setStatus(null);
    input.focus();
  }

  function close() {
    clearTimeout(timer);
    ctrl?.abort();
    panel.hidden = true;
    document.getElementById('btn-search').focus({ preventScroll: true });
  }

  input.addEventListener('input', update);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!items.length) return;
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      draw();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      pick(active);
    } else if (e.key === 'Escape') {
      close();
    }
  });
  document.getElementById('search-close').addEventListener('click', close);

  return { open, close, get isOpen() { return !panel.hidden; } };
}
