import test from 'node:test';
import assert from 'node:assert/strict';
import {compactValue, pageRows} from '../src/pages/measurements/resultView.ts';

test('1020 state IDs never expand in nested display values and source stays intact', () => {
  const ids = Array.from({length: 1020}, (_, i) => `state-${i}`);
  const source = {pool: {state_ids: ids, g_min_s: 0.0001}};
  const rendered = JSON.stringify(compactValue(source));
  assert.ok(rendered.includes('1020개'));
  assert.ok(!rendered.includes('state-1019'));
  assert.equal(source.pool.state_ids.length, 1020);
  assert.ok(rendered.length < 200);
});
test('24k raw rows page without omission or accumulated DOM rows', () => {
  const source = Array.from({length: 24000}, (_, i) => i);
  const visited: number[] = [];
  for (let i = 0; i < 480; i++) {
    const page = pageRows(source, i);
    assert.equal(page.rows.length, 50);
    visited.push(...page.rows);
  }
  assert.deepEqual(visited, source);
  assert.equal(pageRows(source, 999).page, 479);
  assert.equal(pageRows([], 9).page, 0);
  assert.deepEqual(pageRows([], 9).rows, []);
});
