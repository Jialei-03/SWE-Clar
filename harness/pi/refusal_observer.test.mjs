import assert from 'node:assert/strict';
import {refusalFromEvent,observeAnthropicRefusals} from './refusal_observer.mjs';
assert.equal(refusalFromEvent({stop_reason:'end_turn'}),null);
assert.deepEqual(refusalFromEvent({delta:{stop_reason:'refusal',stop_details:{category:'reasoning_extraction'}}}),
 {code:'provider_refusal',type:'refusal',category:'reasoning_extraction'});
assert.equal(refusalFromEvent({stop_reason:'refusal',stop_details:{category:'secret data'}}).category,null);
const data='data: {"type":"message_delta","delta":{"stop_reason":"refusal","stop_details":{"category":"reasoning_extraction"}}}\n\n';
const get=observeAnthropicRefusals(async()=>new Response(data,{headers:{'content-type':'text/event-stream'}}));
const r=await fetch('https://example.test/providers/anthropic/v1/messages');
assert.equal(await r.text(),data);
assert.equal((await get()).category,'reasoning_extraction');
console.log('refusal metadata and unmodified response: passed');
