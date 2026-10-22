import test from 'node:test';
import assert from 'node:assert/strict';
import { requireConfiguredEndpoint } from './endpoint_config.mjs';
test('missing endpoint is rejected instead of falling back to a consumer service', () => {
  for (const base_url of [undefined, null, '', '  ']) {
    assert.throws(() => requireConfiguredEndpoint({base_url}), /Configure base_url/);
  }
});
test('explicit endpoint is preserved', () => {
  assert.equal(requireConfiguredEndpoint({base_url: 'https://api.example.invalid/v1'}), 'https://api.example.invalid/v1');
});
