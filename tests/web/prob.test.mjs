// node --test tests/web/   (або: deno test tests/web/)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { fromApi, query } from '../../web/js/prob.js';

const SET = { shopMean: 60, shopSd: 15, waitMax: 0, openDelay: 0 };

test('query: хвилини округлені й обрізані до меж API', () => {
  const q = new URLSearchParams(query(212.6, { ...SET, shopMean: 5, waitMax: 90 }));
  assert.equal(q.get('travel'), '180');
  assert.equal(q.get('shop_mean'), '20');
  assert.equal(q.get('wait_max'), '60');
  assert.equal(q.get('depart_in'), '0');
});

test('fromApi: p == null → немає даних', () => {
  assert.deepEqual(fromApi({ p: null, band: null, curve: [], best: null }), { nodata: true });
  assert.deepEqual(fromApi(null), { nodata: true });
});

test('fromApi: точки кривої без p відкидаються', () => {
  const r = fromApi({
    p: 0.5, band: [0.4, 0.6], wait: null,
    curve: [{ depart_in: 0, p: 0.5 }, { depart_in: 5, p: null }], best: { depart_in: 0, p: 0.5 },
  });
  assert.deepEqual(r.curve, [{ depart_in: 0, p: 0.5 }]);
  assert.equal(r.best.p, 0.5);
});

test('fromApi: без best — без кривої', () => {
  const r = fromApi({ p: 0.5, band: [0.4, 0.6], curve: [], best: null });
  assert.deepEqual([r.curve, r.best], [null, null]);
});
