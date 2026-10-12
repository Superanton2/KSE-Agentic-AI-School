// node --test tests/web/   (або: deno test tests/web/)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cacheKey, createRouter, fallbackTravel, haversineKm, osrmUrl } from '../../web/js/route.js';

const STORE = { id: 'w1', lat: 50.48664, lon: 30.51683 };
const START = [50.4392, 30.5169];
const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));

function fakeFetch(durationSec, { fail = false } = {}) {
  const calls = [];
  const fn = async (url) => {
    calls.push(url);
    if (fail) throw new Error('offline');
    return { ok: true, json: async () => ({ code: 'Ok', routes: [{ duration: durationSec, distance: 7000 }] }) };
  };
  fn.calls = calls;
  return fn;
}

test('haversine: Kyiv centre → Metro Bandery ≈ 5.3 km', () => {
  assert.ok(Math.abs(haversineKm(START, [STORE.lat, STORE.lon]) - 5.27) < 0.05);
});

test('fallback = straight line × 1.4 at 25 km/h, flagged approximate', () => {
  const r = fallbackTravel(START, [STORE.lat, STORE.lon]);
  assert.equal(r.approx, true);
  assert.ok(Math.abs(r.minutes - (haversineKm(START, [STORE.lat, STORE.lon]) * 1.4 / 25) * 60) < 1e-9);
});

test('OSRM url is lon,lat order with overview=false', () => {
  assert.equal(osrmUrl(START, STORE),
    'https://routing.openstreetmap.de/routed-car/route/v1/driving/30.51690,50.43920;30.51683,50.48664?overview=false');
});

test('cache key: ~200 m rounding of the start, store id included', () => {
  assert.equal(cacheKey([50.4392, 30.5160], 'a'), cacheKey([50.4396, 30.5165], 'a')); // одна клітинка ~200 м
  assert.notEqual(cacheKey([50.4392, 30.5169], 'a'), cacheKey([50.4430, 30.5169], 'a'));
  assert.notEqual(cacheKey(START, 'a'), cacheKey(START, 'b'));
});

test('OSRM answer → minutes, not approximate; second call is served from cache', async () => {
  const f = fakeFetch(17 * 60);
  const travel = createRouter({ fetchImpl: f });
  assert.deepEqual(await travel(START, STORE), { minutes: 17, km: 7, approx: false });
  assert.equal((await travel([50.4393, 30.517], STORE)).minutes, 17);
  assert.equal(f.calls.length, 1);
});

test('network error → fallback estimate, and it is not cached', async () => {
  const f = fakeFetch(0, { fail: true });
  const travel = createRouter({ fetchImpl: f, minInterval: 0 });
  assert.equal((await travel(START, STORE)).approx, true);
  await travel(START, STORE);
  assert.equal(f.calls.length, 2);
});

test('throttle: at most one request per interval, superseded calls resolve to null', async () => {
  const f = fakeFetch(600);
  const travel = createRouter({ fetchImpl: f, minInterval: 50 });
  await travel(START, STORE);                               // t=0: goes out immediately
  const a = travel([50.40, 30.60], STORE);                  // within the interval: waits…
  const b = travel([50.41, 30.61], STORE);                  // …and is replaced by this one
  assert.equal(await a, null);
  assert.equal((await b).minutes, 10);
  assert.equal(f.calls.length, 2);
  assert.ok(f.calls[1].includes('30.61000,50.41000'));
  await tick();
});
