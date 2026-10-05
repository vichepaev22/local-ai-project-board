const test=require('node:test');
const assert=require('node:assert/strict');
const status=require('../execution-status.js');
const events=require('../motion-events.js');
const now=Date.parse('2026-09-07T10:00:00Z');
const context={now,lastLoadedAt:now};
const task=(state,extra={})=>({id:'q1',projectId:'p1',status:state,lastEventAt:new Date(now).toISOString(),...extra});
const project=queue=>status.project('p1',queue,context);

test('only running evidence yields running; dispatch and queue are separate',()=>{
  for(const [input,expected] of [['running','running'],['dispatching','dispatching'],['queued','queued'],['completed','done']])assert.equal(project([task(input)]).kind,expected);
});
test('waiting is explicit, never a running light',()=>{
  for(const s of ['waiting-user','waiting-busy','blocked-external-access'])assert.equal(project([task(s)]).kind,'waiting');
});
test('missing snapshot is unknown, not an empty or running queue',()=>{
  assert.equal(status.project('p1',[task('running')],{now,lastLoadedAt:0}).kind,'unknown');
});
test('failed poll, stale snapshot and old or absent event stop running indication',()=>{
  for(const ctx of [{...context,loadError:true},{...context,lastLoadedAt:now-90001}])assert.equal(status.project('p1',[task('running')],ctx).kind,'stale');
  for(const extra of [{isStale:true},{lastEventAt:new Date(now-120001).toISOString()},{lastEventAt:null}])assert.equal(project([task('running',extra)]).kind,'stale');
});
test('new evidence restores running',()=>{
  const q=task('running');assert.equal(status.project('p1',[q],{...context,loadError:true}).kind,'stale');assert.equal(project([q]).kind,'running');
});
test('duplicate failures count once per project; only latest terminal status counts',()=>{
  const queue=[task('failed',{id:'old',lastEventAt:new Date(now-1000).toISOString()}),task('failed')];
  assert.deepEqual(status.summary([{id:'p1'}],queue,context).error,['p1']);
  queue.push(task('completed',{id:'new',lastEventAt:new Date(now+1000).toISOString()}));
  assert.deepEqual(status.summary([{id:'p1'}],queue,context).error,[]);
});
test('active task outranks historical result; simultaneous states remain discoverable',()=>{
  const queue=[task('completed'),task('running',{id:'run'}),task('waiting-user',{id:'wait'})];
  const groups=status.summary([{id:'p1'}],queue,context);assert.deepEqual(groups.running,['p1']);assert.deepEqual(groups.waiting,['p1']);assert.deepEqual(groups.done,[]);
  assert.equal(project(queue).kind,'waiting');
});
test('waiting busy is not confused with waiting for an answer',()=>{
  assert.equal(project([task('waiting-busy')]).label,'Диалог занят');assert.equal(project([task('waiting-user')]).label,'Нужен ваш ответ');
});
test('known errors have concise explanations and generic errors stay bounded',()=>{
  assert.match(status.errorText(task('failed',{error:JSON.stringify({detail:"The model requires a newer version of Codex"})})),/новая версия/);
  assert.match(status.errorText(task('failed',{error:'failed to deserialize: unknown variant'})),/формат/);
  assert.ok(status.errorText(task('failed',{error:'a'.repeat(3000)})).length<=220);
});
test('relative timestamps use event time and never invent heartbeat',()=>{
  assert.equal(status.relative(new Date(now-12000).toISOString(),now),'сигнал 12 с назад');
  assert.equal(status.relative(null,now),'время сигнала неизвестно');
});
test('signal flash requires a new running event, skips initial and repeated snapshots',()=>{
  const q=task('running'),previous=new Map([[q.id,{status:'running',lastEventAt:new Date(now-1000).toISOString()}]]);
  assert.equal(events.diff(null,[q]).length,0);assert.equal(events.diff(previous,[q])[0].kind,'signal');
  assert.equal(events.diff(new Map([[q.id,q]]),[q]).length,0);
  assert.equal(events.diff(previous,[{...q,isStale:true}]).some(e=>e.kind==='signal'),false);
  assert.equal(events.diff(previous,[task('failed')]).some(e=>e.kind==='signal'),false);
});
test('interpretation is read-only and does not create percentage progress',()=>{
  const queue=[task('running')],before=JSON.stringify(queue);assert.equal(project(queue).progress,undefined);assert.equal(JSON.stringify(queue),before);
});
