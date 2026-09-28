const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');

const html = readFileSync(join(__dirname, '..', 'web', 'templates', 'settings.html'), 'utf8');
const code = html.match(/async function muatPemakaianGemini\(\) \{[\s\S]*?\n\}/)?.[0];

test('pemakaian Gemini tampil sebagai biaya per model, bukan input harga', async () => {
  assert.ok(code);
  assert.match(html, /Setara biaya API berbayar/);
  const nodes = Object.fromEntries([
    'usage-period', 'usage-requests', 'usage-lifetime-total', 'usage-lifetime-cost',
    'usage-model-rows', 'usage-note',
  ].map(id => [id, { textContent: '', innerHTML: '', value: 'all' }]));
  const document = { getElementById: id => nodes[id] };
  const display = new Function('document', 'fetch', 'esc', `${code}; return muatPemakaianGemini()`);
  const response = data => async () => ({ ok: true, json: async () => ({
    requests: 2, total_tokens: 116998, equivalent_cost_usd: 0.08,
    unpriced_tokens: 0, pricing: { as_of: '2026-09-28' },
    models: [{ model: 'gemini-3.5-transcribe', requests: 2, input_tokens: 100000,
      output_tokens: 16998, total_tokens: 116998, unpriced_tokens: 0,
      equivalent_cost_usd: 0.08, price_status: 'listed' }], ...data,
  }) });
  const esc = s => s;

  await display(document, response({} ), esc);
  assert.equal(nodes['usage-lifetime-total'].textContent, '116.998 token');
  assert.equal(nodes['usage-lifetime-cost'].textContent, '~US$0,08');
  assert.match(nodes['usage-model-rows'].innerHTML, /gemini-3.5-transcribe/);

  await display(document, response({ unpriced_tokens: 116998 }), esc);
  assert.equal(nodes['usage-lifetime-cost'].textContent, 'Belum bisa dihitung');
});
