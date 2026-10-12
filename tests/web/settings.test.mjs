// node --test tests/web/   (або: deno test tests/web/)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { DEFAULTS, loadSettings, sanitize, saveSettings } from '../../web/js/settings.js';
import { horizonBucket, unsureReason } from '../../web/js/unsure.js';

const memStorage = () => {
  const m = new Map();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v)), m };
};

test('settings: defaults from the spec', () => {
  assert.deepEqual({ ...DEFAULTS }, { shopMean: 60, shopSd: 15, waitMax: 0, openDelay: 0, manualTravel: null, venue: 'metro' });
});

test('settings: out-of-range and junk values are clamped or dropped', () => {
  const s = sanitize({ shopMean: 500, shopSd: -3, waitMax: 17.4, openDelay: 'x', manualTravel: 0, venue: 'mcdonalds', lat: 50.4 });
  assert.deepEqual(s, { shopMean: 120, shopSd: 0, waitMax: 17, openDelay: 0, manualTravel: 1, venue: 'metro' });
  assert.deepEqual(sanitize(null), { ...DEFAULTS });
});

test('settings: round-trip through storage; broken or throwing storage → defaults', () => {
  const st = memStorage();
  saveSettings({ ...DEFAULTS, shopMean: 45, manualTravel: 25 }, st);
  assert.equal(loadSettings(st).shopMean, 45);
  assert.equal(loadSettings(st).manualTravel, 25);
  st.m.set('vstyhnu.settings.v1', '{not json');
  assert.deepEqual(loadSettings(st), { ...DEFAULTS });
  const throwing = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  assert.deepEqual(loadSettings(throwing), { ...DEFAULTS });
  assert.doesNotThrow(() => saveSettings(DEFAULTS, throwing));
});

test('unsure: trust a short trip with a narrow band and positive skill', () => {
  assert.equal(unsureReason({ travel: 18, shop: 60, band: [0.66, 0.81], skill: { '0-30': 0.2 } }), null);
});

test('unsure: trip beyond the 120-min horizon', () => {
  assert.equal(unsureReason({ travel: 50, shop: 75, band: [0.6, 0.7] }), 'horizon');
  assert.equal(unsureReason({ travel: 20, wait: 25, openDelay: 20, shop: 60 }), 'horizon');
});

test('unsure: band wider than 30 pp', () => {
  assert.equal(unsureReason({ travel: 18, shop: 60, band: [0.3, 0.62] }), 'band');
  assert.equal(unsureReason({ travel: 18, shop: 60, band: [0.3, 0.6] }), null);
});

test('unsure: negative skill at the horizon of arrival; missing skill is not a reason', () => {
  const skill = { '0-30': 0.21, '30-60': -0.05, '60-120': -0.02 };
  assert.equal(unsureReason({ travel: 18, shop: 60, skill }), null);
  assert.equal(unsureReason({ travel: 35, shop: 60, skill }), 'skill');
  assert.equal(unsureReason({ travel: 35, shop: 60, skill: { '30-60': null } }), null);
  assert.equal(horizonBucket(29.9), '0-30');
  assert.equal(horizonBucket(60), '60-120');
});
