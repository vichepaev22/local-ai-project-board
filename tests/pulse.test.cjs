const {test}=require('node:test');
const assert=require('node:assert/strict');
const motion=require('../motion-events.js');
const entry=(kind,id='a',projectId='one')=>({id,projectId,kind});
function tracker(){assert.equal(typeof motion.createPulseTracker,'function','Pulse must track queue transitions, not button clicks');return motion.createPulseTracker();}

test('first snapshot establishes baseline without replaying old outcomes',()=>{
  const t=tracker();t.observe([entry('done'),entry('error','b')]);assert.deepEqual(t.take(),[]);
});
test('sending, running and completion preserve actual source and target',()=>{
  const t=tracker();t.observe([entry('queued')]);
  for(const [from,to] of [['queued','dispatching'],['dispatching','running'],['running','done']]){
    t.observe([entry(to)]);assert.deepEqual(t.take(),[{id:'a',projectId:'one',from,to}]);
  }
});
test('failed dispatch moves to error, never to done',()=>{
  const t=tracker();t.observe([entry('dispatching')]);t.observe([entry('error')]);assert.equal(t.take()[0].to,'error');
});
test('polling and repeated filtering do not retrigger a transition',()=>{
  const t=tracker();t.observe([entry('running')]);t.observe([entry('done')]);t.take();t.observe([entry('done')]);assert.deepEqual(t.take(),[]);
});
test('stale or failed page snapshot cannot consume unseen outcomes',()=>{
  const t=tracker();t.observe([entry('running')]);t.observe([entry('done')],false);assert.deepEqual(t.take(),[]);t.observe([entry('done')]);assert.equal(t.take()[0].to,'done');
});
test('hidden-tab changes coalesce until they can be shown',()=>{
  const t=tracker();t.observe([entry('queued')]);t.observe([entry('dispatching')]);t.observe([entry('running')]);t.observe([entry('done')]);
  assert.equal(t.size,1);assert.deepEqual(t.take(),[{id:'a',projectId:'one',from:'queued',to:'done'}]);assert.equal(t.size,0);
});
test('interrupted animation can be shown once after returning',()=>{
  const t=tracker();t.observe([entry('running')]);t.observe([entry('error')]);const pending=t.take();t.putBack(pending);assert.deepEqual(t.take(),pending);assert.deepEqual(t.take(),[]);
});
test('more recent event supersedes an interrupted older event',()=>{
  const t=tracker();t.observe([entry('running')]);t.observe([entry('error')]);const old=t.take();t.observe([entry('dispatching')]);t.putBack(old);assert.equal(t.take()[0].to,'dispatching');
});
test('parallel tasks with unchanged aggregate counts still generate events',()=>{
  const t=tracker();t.observe([entry('running','a'),entry('queued','b','two')]);t.observe([entry('done','a'),entry('running','b','two')]);assert.deepEqual(t.take().map(e=>e.to),['done','running']);
});
test('new tasks after baseline have no invented previous stage',()=>{
  const t=tracker();t.observe([]);t.observe([entry('dispatching')]);assert.equal(t.take()[0].from,null);
});
