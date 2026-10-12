// node --test tests/web/   (або: deno test tests/web/)
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { matchStores, normalize, photonItem, photonUrl } from '../../web/js/search.js';

const STORES = [
  { id: 'a', name: 'METRO Київ', address: 'проспект Степана Бандери, 26-В' },
  { id: 'b', name: 'METRO Київ', address: 'вулиця Сержа Лифаря, 2-А' },
  { id: 'c', name: 'METRO', address: 'Кільцева дорога, 1-В' },
];

test('normalize: case, apostrophes, spaces', () => {
  assert.equal(normalize('  Сол’ЯНСЬКА   вул '), "сол'янська вул");
});

test('stores: every query word must match name + address', () => {
  assert.deepEqual(matchStores(STORES, 'бандери').map((s) => s.id), ['a']);
  assert.deepEqual(matchStores(STORES, 'metro лифаря').map((s) => s.id), ['b']);
  assert.deepEqual(matchStores(STORES, 'metro').map((s) => s.id), ['a', 'b', 'c']);
  assert.deepEqual(matchStores(STORES, '   '), []);
});

test('photon url: query text and Kyiv bbox only — no user coordinates', () => {
  const u = new URL(photonUrl('Хрещатик 1'));
  assert.equal(u.origin, 'https://photon.komoot.io');
  assert.deepEqual([...u.searchParams.keys()].sort(), ['bbox', 'limit', 'q']);
  assert.equal(u.searchParams.get('q'), 'Хрещатик 1');
});

test('photon item: title, subtitle, [lat, lon]; junk is dropped', () => {
  const it = photonItem({
    geometry: { coordinates: [30.52, 50.447] },
    properties: { name: 'Хрещатик', street: 'вулиця Хрещатик', district: 'Клов', city: 'Київ' },
  });
  assert.equal(it.title, 'Хрещатик');
  assert.ok(it.sub.includes('вулиця Хрещатик') && it.sub.includes('Київ'));
  assert.deepEqual(it.latlng, [50.447, 30.52]);

  const addr = photonItem({ geometry: { coordinates: [30.5, 50.4] }, properties: { street: 'вулиця Велика Васильківська', housenumber: '72', city: 'Київ' } });
  assert.equal(addr.title, 'вулиця Велика Васильківська, 72');

  assert.equal(photonItem({ geometry: { coordinates: [30.5, 50.4] }, properties: {} }), null);
  assert.equal(photonItem({ properties: { name: 'x' } }), null);
});
