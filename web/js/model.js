// Сторінка «Про модель»: текст — з i18n, цифри — з /api/model-card. Поки моделі нема — плейсхолдери.
import { getModelCard } from './api.js';
import { applyI18n, loadLang, t } from './i18n.js';

const $ = (id) => document.getElementById(id);
const fmtNum = (v) => (typeof v === 'number' ? v.toFixed(3) : String(v ?? '—'));

// metrics: масив однорідних об'єктів → таблиця (стовпці — ключі першого рядка).
function metricsTable(rows) {
  const cols = Object.keys(rows[0]);
  const table = document.createElement('table');
  const head = table.createTHead().insertRow();
  for (const c of cols) {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = c;
    head.append(th);
  }
  const body = table.createTBody();
  for (const r of rows) {
    const tr = body.insertRow();
    for (const c of cols) {
      const td = tr.insertCell();
      td.textContent = fmtNum(r[c]);
      if (typeof r[c] === 'number') td.className = 'num';
    }
  }
  return table;
}

async function main() {
  await loadLang('uk');
  applyI18n();

  let card;
  try { card = await getModelCard(); } catch { return; }

  if (card.test_period) $('mc-period').textContent = t('model.acc.period', { from: card.test_period[0], to: card.test_period[1] });
  if (card.metrics?.length) $('mc-metrics').replaceChildren(metricsTable(card.metrics));
  // Графік калібрування (inline SVG) — коли буде формат model-card.calibration.
}

main();
