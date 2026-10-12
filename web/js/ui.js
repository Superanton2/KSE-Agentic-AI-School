// Рендер статусу й картки результату. Лише textContent / createElementNS — жодного innerHTML.
import { t } from './i18n.js';

const $ = (id) => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const TZ = 'Europe/Kyiv';

export const fmtTime = (ms) =>
  new Intl.DateTimeFormat('uk-UA', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(ms);

export function fmtDur(ms) {
  const min = Math.floor(Math.max(0, ms) / 60_000);
  if (min < 1) return t('dur.lt1');
  if (min < 60) return t('dur.min', { m: min });
  return t('dur.hm', { h: Math.floor(min / 60), m: min % 60 });
}

export const pClass = (p) => (p >= 0.75 ? 'good' : p >= 0.5 ? 'mid' : 'bad');
const pct = (p) => Math.round(p * 100);

export function renderStatus(state, stale, now = Date.now()) {
  const el = $('status');
  const kind = stale ? 'stale' : state.status === 'alert' ? (state.level === 'red' ? 'red' : 'yellow') : 'calm';
  el.className = `pill status is-${kind}`;
  $('status-ico').setAttribute('href', stale ? '#i-stale' : state.status === 'alert' ? '#i-alert' : '#i-calm');
  $('status-text').textContent = stale ? t('status.stale') : t(`status.${state.status}`);
  $('status-timer').textContent = stale || !state ? '' : fmtDur(now - Date.parse(state.since));
  el.querySelector('.sep').hidden = stale;

  const asof = state ? t('asof', { time: fmtTime(Date.parse(state.data_as_of)) }) : '';
  const level = !stale && state.status === 'alert' && state.level ? `${t(`status.level.${state.level}`)} · ` : '';
  $('asof').textContent = level + asof;
}

// r: { store, from?:{me}|{label}, p, band:[lo,hi], travel, approx, manual, shop, wait?:{median,p80},
//      curve:[{depart_in,p}], best, unsure, unsureReason, nodata, nostart }
export function renderCard(r, now = Date.now()) {
  const card = $('card');
  if (!r) { card.hidden = true; return; }
  const kind = r.nostart ? 'nostart' : r.nodata ? 'nodata' : r.unsure ? 'unsure' : pClass(r.p);
  const noProb = r.nostart || r.nodata;
  card.className = `card is-${kind}`;
  card.hidden = false;

  $('card-store').textContent = r.store.name;
  $('card-addr').textContent = r.store.address;
  $('card-p').textContent = r.nostart ? t('card.nostart') : r.nodata ? t('card.nodata') : `${pct(r.p)}%`;
  $('card-word').textContent = noProb ? '' : t(`card.word.${kind}`);
  const band = noProb ? '' : t('card.band', { lo: pct(r.band[0]), hi: pct(r.band[1]) });
  $('card-band').textContent = r.unsureReason ? `${band} · ${t(`unsure.${r.unsureReason}`)}` : band;
  $('card-band').hidden = noProb;
  $('card-cta').hidden = !r.nostart;

  const from = $('card-from');
  from.hidden = !r.from;
  if (r.from) from.textContent = r.from.me ? t('card.from_me') : t('card.from', { label: r.from.label });

  const trip = $('card-trip');
  trip.hidden = !!r.nostart;
  if (!r.nostart) {
    const tripKey = r.manual ? 'card.trip_manual' : r.approx ? 'card.trip_approx' : 'card.trip';
    trip.textContent = t(tripKey, { travel: Math.round(r.travel), shop: Math.round(r.shop) });
  }
  $('card-note').hidden = !!(r.manual || r.nostart); // затори — лише для маршруту OSRM

  const wait = $('card-wait');
  wait.hidden = !r.wait || noProb;
  if (r.wait) wait.textContent = t('card.wait', { wait: Math.round(r.wait.median), p80: Math.round(r.wait.p80) });

  const curve = card.querySelector('.curve');
  curve.hidden = noProb || !r.curve;
  if (!curve.hidden) {
    renderCurve($('card-curve'), r.curve, r.best);
    const best = $('card-best');
    best.textContent = '';
    const [pre, post] = t('card.best', { time: '\u0000', p: pct(r.best.p) }).split('\u0000');
    const b = document.createElement('b');
    b.textContent = fmtTime(now + r.best.depart_in * 60_000);
    best.append(pre, b, post);
  }
}

// Міні-крива: стовпчик на кожну точку виїзду (0, 5, …, 60 хв), висота = P(успіх).
function renderCurve(svg, curve, best) {
  svg.replaceChildren();
  const W = 130, H = 34, n = curve.length, gap = 2;
  const bw = (W - gap * (n - 1)) / n;
  curve.forEach((pt, i) => {
    const h = Math.max(1.5, pt.p * (H - 2));
    const r = document.createElementNS(SVG, 'rect');
    r.setAttribute('x', (i * (bw + gap)).toFixed(2));
    r.setAttribute('y', (H - 1 - h).toFixed(2));
    r.setAttribute('width', bw.toFixed(2));
    r.setAttribute('height', h.toFixed(2));
    r.setAttribute('rx', '1');
    r.setAttribute('class', `bar ${pClass(pt.p)}${pt.depart_in === best.depart_in ? ' best' : ''}`);
    svg.append(r);
  });
  const axis = document.createElementNS(SVG, 'line');
  for (const [k, v] of Object.entries({ x1: 0, x2: W, y1: H - 0.5, y2: H - 0.5, class: 'axis' })) axis.setAttribute(k, v);
  svg.append(axis);
}

// Банер «Оголошено тривогу» на 10 с — без звуку й вібрації.
let bannerTimer = null;
export function showBanner(level) {
  const el = $('banner');
  el.className = `banner is-${level === 'red' ? 'red' : 'yellow'}`;
  $('banner-text').textContent = level ? `${t('banner.alert')} · ${t(`status.level.${level}`)}` : t('banner.alert');
  el.hidden = false;
  clearTimeout(bannerTimer);
  bannerTimer = setTimeout(() => { el.hidden = true; }, 10_000);
}
