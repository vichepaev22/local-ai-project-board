const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const Journal=fs.existsSync(require('node:path').join(__dirname,'../queue-journal.js'))?require('../queue-journal.js'):{};
const rows=[
  {id:'run',projectId:'one',status:'running',createdAt:'2026-09-04T10:00:00'},
  {id:'done',projectId:'one',status:'completed',completedAt:'2026-09-03T10:00:00'},
  {id:'fail',projectId:'two',status:'failed',createdAt:'2026-09-02T10:00:00'},
  {id:'old',projectId:'two',status:'completed',createdAt:'2026-09-01T10:00:00',archivedAt:'2026-09-07T10:00:00'},
  {id:'queued',projectId:'one',status:'queued',createdAt:'2026-09-05T10:00:00'},
];
function view(options){assert.equal(typeof Journal.view,'function','Journal must separate current, completed and archived records');return Journal.view(rows,options).map(q=>q.id);}
test('tabs partition the queue without losing failed attempts',()=>{
  assert.deepEqual(view({tab:'current'}),['queued','run','fail']);
  assert.deepEqual(view({tab:'done'}),['done']);assert.deepEqual(view({tab:'archive'}),['old']);
});
test('project, status and inclusive date boundaries combine',()=>{
  assert.deepEqual(view({tab:'current',project:'two',status:'failed',from:'2026-09-02',to:'2026-09-02'}),['fail']);
  assert.deepEqual(view({tab:'current',project:'one',status:'failed'}),[]);
});
test('archived records are filtered by original event date, not filing date',()=>{
  assert.deepEqual(view({tab:'archive',from:'2026-09-01',to:'2026-09-01'}),['old']);
  assert.deepEqual(view({tab:'archive',from:'2026-09-07'}),[]);
});
test('only completed, failed and interrupted records may be archived',()=>{
  assert.equal(typeof Journal.canArchive,'function');
  for(const status of ['completed','failed','interrupted'])assert.equal(Journal.canArchive({status}),true);
  for(const status of ['queued','running','dispatching','waiting-user','waiting-busy','blocked-external-access'])assert.equal(Journal.canArchive({status}),false);
  assert.equal(Journal.canArchive(rows[3]),false);
});
test('archive and send selections cannot be confused, even with stale selected IDs',()=>{
  assert.equal(typeof Journal.selection,'function');const ids=new Set(rows.map(q=>q.id));
  assert.deepEqual(Journal.selection(rows,ids,'send',new Set(['queued'])),['queued']);
  assert.deepEqual(Journal.selection(rows,ids,'archive'),['done','fail']);
  assert.deepEqual(Journal.selection(rows,ids,'restore'),['old']);
});
test('sorting and filtering leave original queue untouched',()=>{
  const original=JSON.stringify(rows);view({tab:'done'});assert.equal(JSON.stringify(rows),original);
});
