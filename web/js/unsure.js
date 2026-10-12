// Стан «Дуже неточно»: коли числу ймовірності довіряти не можна.
export const HORIZON_MIN = 120;
export const MAX_BAND_PP = 30;

// Горизонт прогнозу — момент відкриття магазину (прибуття + очікування відбою + затримка відкриття):
// модель має передбачити, чи почнеться тривога у вікні покупок, що стартує тоді.
export function horizonBucket(openMin) {
  if (openMin < 30) return '0-30';
  if (openMin < 60) return '30-60';
  return '60-120';
}

// → null (довіряємо) або причина: 'horizon' | 'band' | 'skill'.
export function unsureReason({ travel, wait = 0, openDelay = 0, shop, band, skill }) {
  const open = travel + wait + (wait > 0 ? openDelay : 0);
  if (open + shop > HORIZON_MIN) return 'horizon';
  if (band && (band[1] - band[0]) * 100 > MAX_BAND_PP) return 'band';
  const s = skill?.[horizonBucket(open)];
  if (typeof s === 'number' && s < 0) return 'skill';
  return null;
}
