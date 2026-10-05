const {test} = require('node:test');
const assert = require('node:assert/strict');
const mode = require('../harness-mode.js');
test('manual is the safe default and never enables dispatch', () => {
  assert.equal(mode.policy({}, {}).allowed, false);
  assert.equal(mode.policy({kind:'manual',online:true}, {dispatchAllowed:true}).allowed, false);
});
test('Hermes uses readiness, never a fabricated Codex quota', () => {
  assert.deepEqual(mode.policy({kind:'hermes',online:true}, {limitEnforced:false,dispatchAllowed:true,isLive:false}), {kind:'hermes',name:'Hermes',allowed:true,capacity:Infinity});
  assert.equal(mode.policy({kind:'hermes',online:false}, {dispatchAllowed:false}).allowed, false);
});
test('Codex needs a live nonzero quota, zero cannot become one', () => {
  const bridge={kind:'codex',online:true};
  const budget={isLive:true,fiveHour:{remainingPercent:0},weekly:{remainingPercent:90}};
  assert.equal(mode.policy(bridge,budget).allowed, false);
  budget.fiveHour.remainingPercent=30;
  assert.equal(mode.policy(bridge,budget).capacity, 30);
  assert.equal(mode.policy(bridge,{...budget,isLive:false}).allowed,false);
});
test('copying requests keeps literal shell characters and grants no publication', () => {
  const prompt=mode.prompt({name:'Example'},[{kind:'comment',text:'$(echo unsafe); `test`; "quote"'}]);
  assert.ok(prompt.includes('$(echo unsafe); `test`; "quote"'));
  assert.match(prompt,/Не публикуй/);
});
