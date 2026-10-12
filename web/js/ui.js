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

// r: { store, p, band:[lo,hi], travel, approx, shop, wait?:{median,p80}, curve:[{depart_in,p}], best, unsure, nodata }
export function renderCard(r, now = Date.now()) {
  const card = $('card');
  if (!r) { card.hidden = true; return; }
  const kind = r.nodata ? 'nodata' : r.unsure ? 'unsure' : pClass(r.p);
  card.className = `card is-${kind}`;
  card.hidden = false;

  $('card-store').textContent = r.store.name;
  $('card-addr').textContent = r.store.address;
  $('card-p').textContent = r.nodata ? t('card.nodata') : `${pct(r.p)}%`;
  $('card-word').textContent = r.nodata ? '' : t(`card.word.${kind}`);
  $('card-band').textContent = r.nodata ? '' : t('card.band', { lo: pct(r.band[0]), hi: pct(r.band[1]) });
  $('card-band').hidden = r.nodata;
  $('card-trip').textContent = t(r.approx ? 'card.trip_approx' : 'card.trip', { travel: Math.round(r.travel), shop: Math.round(r.shop) });

  const wait = $('card-wait');
  wait.hidden = !r.wait || r.nodata;
  if (r.wait) wait.textContent = t('card.wait', { wait: Math.round(r.wait.median), p80: Math.round(r.wait.p80) });

  const curve = card.querySelector('.curve');
  curve.hidden = r.nodata || !r.curve;
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
