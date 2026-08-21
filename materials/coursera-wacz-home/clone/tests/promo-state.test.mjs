import assert from 'node:assert/strict';
import test from 'node:test';

import { createPromoState } from '../static/promo-state.js';


test('manual navigation wraps through all three promotional positions', () => {
  const changes = [];
  const state = createPromoState({
    itemCount: 3,
    visibleCount: 2,
    onChange: (snapshot) => changes.push(snapshot),
  });

  assert.equal(state.getIndex(), 0);
  assert.deepEqual(changes.at(-1), { index: 0, visibleIndexes: [0, 1] });

  state.next();
  assert.equal(state.getIndex(), 1);
  assert.deepEqual(changes.at(-1), { index: 1, visibleIndexes: [1, 2] });

  state.next();
  assert.equal(state.getIndex(), 2);
  assert.deepEqual(changes.at(-1), { index: 2, visibleIndexes: [2, 0] });

  state.next();
  assert.equal(state.getIndex(), 0);
});


test('previous and direct selection normalize to a valid position', () => {
  const state = createPromoState({ itemCount: 3, visibleCount: 2, onChange: () => {} });

  state.previous();
  assert.equal(state.getIndex(), 2);

  state.goTo(9);
  assert.equal(state.getIndex(), 0);

  state.goTo(-1);
  assert.equal(state.getIndex(), 2);
});


test('promotional state never advances without a user action', async () => {
  let changeCount = 0;
  const state = createPromoState({
    itemCount: 3,
    visibleCount: 2,
    onChange: () => { changeCount += 1; },
  });

  assert.equal(changeCount, 1);
  await new Promise((resolve) => setTimeout(resolve, 150));

  assert.equal(state.getIndex(), 0);
  assert.equal(changeCount, 1);
});


test('invalid item and visible counts are rejected', () => {
  assert.throws(
    () => createPromoState({ itemCount: 0, visibleCount: 2, onChange: () => {} }),
    /itemCount must be a positive integer/,
  );
  assert.throws(
    () => createPromoState({ itemCount: 3, visibleCount: 4, onChange: () => {} }),
    /visibleCount must be between 1 and itemCount/,
  );
});
