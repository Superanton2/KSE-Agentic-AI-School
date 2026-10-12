// ЗАГЛУШКА. Ймовірність рахує окремий модуль; його контракт ще не зафіксовано.
// Поки — фіксовані числа за поточним статусом, щоб картка мала що показати.
// Вихід: { p, band:[lo,hi], wait?:{median,p80}, curve:[{depart_in,p}], best, unsure? }
const curveFrom = (ps) => ps.map((p, i) => ({ depart_in: i * 5, p }));

const STUB = {
  calm: { p: 0.74, band: [0.66, 0.81], curve: curveFrom([0.74, 0.76, 0.79, 0.81, 0.8, 0.77, 0.72, 0.66, 0.61, 0.58, 0.55, 0.52, 0.5]) },
  yellow: { p: 0.41, band: [0.3, 0.52], wait: { median: 25, p80: 50 }, curve: curveFrom([0.41, 0.46, 0.52, 0.57, 0.61, 0.63, 0.62, 0.6, 0.57, 0.55, 0.52, 0.5, 0.47]) },
  red: { p: 0.28, band: [0.19, 0.4], wait: { median: 34, p80: 58 }, curve: curveFrom([0.28, 0.3, 0.33, 0.37, 0.42, 0.46, 0.49, 0.52, 0.54, 0.53, 0.51, 0.49, 0.46]) },
};

export function estimate({ state, store, travelMin, shopMin }) {
  const s = state?.status === 'alert' ? STUB[state.level === 'red' ? 'red' : 'yellow'] : STUB.calm;
  return { ...s, best: s.curve.reduce((a, b) => (b.p > a.p ? b : a)) };
}
