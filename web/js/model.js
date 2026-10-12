// Сторінка «Про модель»: текст — з i18n, усі числа — з /api/model-card (data-n="ключ" → t(ключ, vars)).
import { getModelCard } from './api.js';
import { applyI18n, loadLang, t } from './i18n.js';

const $ = (id) => document.getElementById(id);
const SVG = 'http://www.w3.org/2000/svg';
const pct = (v) => Math.round(v * 100);
const f3 = (v) => v.toFixed(3);
const f4 = (v) => (v > 0 ? '+' : '') + v.toFixed(4);
const f1 = (v) => v.toFixed(1);
const date = (s) => s.split('-').reverse().join('.');

function table(head, rows) {
  const el = document.createElement('table');
  const tr = el.createTHead().insertRow();
  for (const h of head) {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = h;
    tr.append(th);
  }
  const body = el.createTBody();
  for (const r of rows) {
    const row = body.insertRow();
    r.forEach((v, i) => {
      const td = row.insertCell();
      td.textContent = v;
      if (i > 0) td.className = 'num';
    });
  }
  return el;
}

function svg(tag, attrs, parent) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  parent?.append(el);
  return el;
}

// Калібрування продуктового бектесту: прогноз P(успіх) по децилях vs фактична частка вдалих поїздок.
function calibrationChart(cal, model) {
  const W = 320, P = 36, S = W - 2 * P;
  const x = (v) => P + v * S, y = (v) => W - P - v * S;
  const root = svg('svg', { viewBox: `0 0 ${W} ${W}`, role: 'img', 'aria-label': t('model.acc.calib_aria'), class: 'calib' });
  for (const v of [0, 0.25, 0.5, 0.75, 1]) {
    svg('line', { x1: x(0), x2: x(1), y1: y(v), y2: y(v), class: 'grid' }, root);
    svg('text', { x: P - 6, y: y(v) + 4, 'text-anchor': 'end', class: 'tick' }, root).textContent = pct(v);
    svg('text', { x: x(v), y: W - P + 16, 'text-anchor': 'middle', class: 'tick' }, root).textContent = pct(v);
  }
  svg('line', { x1: x(0), y1: y(0), x2: x(1), y2: y(1), class: 'diag' }, root);
  for (const [name, cls] of [['B1', 'ref'], [model, 'main']]) {
    const pts = cal[name] ?? [];
    svg('polyline', { points: pts.map((b) => `${x(b.p_mean)},${y(b.y_mean)}`).join(' '), class: `line ${cls}` }, root);
    for (const b of pts) svg('circle', { cx: x(b.p_mean), cy: y(b.y_mean), r: 3.5, class: `dot ${cls}` }, root);
  }
  svg('text', { x: x(0.5), y: W - 4, 'text-anchor': 'middle', class: 'axis' }, root).textContent = t('model.acc.calib_x');
  const yl = svg('text', { x: 12, y: y(0.5), 'text-anchor': 'middle', class: 'axis', transform: `rotate(-90 12 ${y(0.5)})` }, root);
  yl.textContent = t('model.acc.calib_y');
  const legend = document.createElement('p');
  legend.className = 'doc-meta';
  legend.textContent = t('model.acc.calib_legend', { model });
  return [root, legend];
}

function vars(c) {
  const bt = c.product_backtest;
  const m = c.product_model;
  // бін бектесту, найближчий до ~70%: «кажемо ~X% — встигали в ~Y%»
  const bin = bt.calibration[m].reduce((a, b) => (Math.abs(b.p_mean - 0.7) < Math.abs(a.p_mean - 0.7) ? b : a));
  const [r0, r1, r2] = c.regime.periods;
  const ab = c.drone_ablation;
  return {
    model: m, p: pct(bin.p_mean), y: pct(bin.y_mean), bss: f3(bt.bss_vs_B1), lo: f3(bt.bss_ci[0]), hi: f3(bt.bss_ci[1]),
    n_trips: bt.n_trips, success: pct(bt.success_rate),
    dup: c.data_quality.official_duplicates_pct, dead: date(c.data_quality.official_dead_since),
    s0: f1(r0.starts_per_day), s1: f1(r1.starts_per_day), s2: f1(r2.starts_per_day),
    d0: r0.median_dur_min, d1: r1.median_dur_min, d2: r2.median_dur_min,
    km_median: c.duration.median_min, km_n: c.duration.n, km_from: date(c.duration.km_from),
    from: date(c.test_period[0]), to: date(c.test_period[1]), n_starts: c.n_test_starts,
    val_a: ab.validation_brier.M1a.toFixed(4), val_b: ab.validation_brier.M1b.toFixed(4),
    top_bp: pct(ab.test_top_bin_60.M1b.p), top_by: pct(ab.test_top_bin_60.M1b.y),
    top_ap: pct(ab.test_top_bin_60.M1a.p), top_ay: pct(ab.test_top_bin_60.M1a.y),
    motion_min: ab.motion_course_random_after_min,
    signif: t(c.ablation.significant ? 'model.acc.signif_yes' : 'model.acc.signif_no'),
  };
}

async function main() {
  await loadLang('uk');
  applyI18n();

  let card;
  try { card = await getModelCard(); } catch {
    for (const el of document.querySelectorAll('[data-n]')) el.textContent = t('model.nocard');
    return;
  }
  const v = vars(card);
  for (const el of document.querySelectorAll('[data-n]')) el.textContent = t(el.dataset.n, v);
  $('mc-updated').textContent = t('model.updated', { time: card.updated_at.slice(0, 16).replace('T', ' ') + ' UTC' });
  $('mc-period').textContent = t('model.acc.period', { from: v.from, to: v.to, n: card.n_test_starts });

  const m = card.product_model;
  const bss = (H, name) => card.metrics.find((r) => r.H === H && r.model === name)?.bss_vs_B1;
  $('mc-metrics').replaceChildren(table(
    [t('model.acc.col_h'), t('model.acc.col_bss', { model: m }), t('model.acc.col_ci'), t('model.acc.col_bss', { model: 'M1b' })],
    card.bss_ci.map((r) => [r.H, f3(r.point), `[${f3(r.lo)}, ${f3(r.hi)}]`, f3(bss(r.H, 'M1b'))]),
  ));
  $('mc-calibration').replaceChildren(...calibrationChart(card.product_backtest.calibration, m));
  $('mc-ablation').replaceChildren(table(
    [t('model.acc.col_h'), t('model.acc.col_dbrier'), t('model.acc.col_ci')],
    card.ablation.by_horizon.map((r) => [r.H, f4(r.point), `[${f4(r.lo)}, ${f4(r.hi)}]`]),
  ));
}

main();
