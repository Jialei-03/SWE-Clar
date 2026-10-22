import assert from 'node:assert/strict';
import {test} from 'node:test';
import {withOutputBudget} from './output-budget.mjs';
for (const [api, field] of [['openai-responses','max_output_tokens'],['openai-completions','max_tokens'],['openai-completions','max_completion_tokens'],['anthropic-messages','max_tokens']]) {
  test(`${api}/${field} retains explicit budget and other payload data`, () => {
    const payload = {max_tokens:2, max_completion_tokens:3, max_output_tokens:4, reasoning:{effort:'max'}, messages:[{reasoning_content:'native history'}],tools:[]};
    const original = structuredClone(payload);
    const result = withOutputBudget(payload,{api,maxTokens:128000},{compat:{maxTokensField:field},model_max_output_tokens:32768});
    const expected = {...payload};
    for (const key of ['max_tokens','max_completion_tokens','max_output_tokens']) delete expected[key];
    expected[field]=32768;
    assert.deepEqual(result,expected);assert.deepEqual(payload,original);
  });
}
test('rejects missing budget and unqualified mapping instead of dropping cap',()=>{
  assert.throws(()=>withOutputBudget({}, {api:'openai-responses'}, {}));
  assert.throws(()=>withOutputBudget({}, {api:'unknown',maxTokens:100}, {}));
  assert.throws(()=>withOutputBudget({}, {api:'openai-completions',maxTokens:100}, {}));
});
