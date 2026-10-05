const {test} = require('node:test');
const assert = require('node:assert/strict');
const {resolve} = require('../attention.js');
const {entries} = require('../project-history.js');
const now = Date.parse('2026-09-06T10:00:00Z');
const project = {id:'one', name:'Пилот', goal:'Проверить спрос', nextSteps:['Codex: собрать материалы.', 'Вы: выбрать аудиторию.']};
const ctx = {now, budget:{isLive:true,fiveHour:{remainingPercent:30},weekly:{remainingPercent:40}}};
const q = (status, extra={}) => ({projectId:'one',status,createdAt:'2026-09-06T09:00:00Z',...extra});

test('all six stages have distinct guidance and ready-to-use prompts',()=>{
  const hints=['backlog','sprint','ready','doing','review','done'].map(col=>resolve(project,col,{},[],ctx));
  assert.equal(new Set(hints.map(h=>h.title)).size,6);
  for(const hint of hints){assert.ok(hint.action.trim().length>0);assert.match(hint.prompt,/без отдельного разрешения/);}
  assert.equal(hints[0].action,'выбрать аудиторию.');
});
test('human decision takes precedence over stage, stale state and other running tasks',()=>{
  assert.equal(resolve(project,'done',{},[q('running'),q('waiting-user')],ctx).title,'Нужно ваше решение');
  assert.equal(resolve(project,'doing',{},[q('running',{isStale:true})],ctx).title,'Проверьте связь');
  assert.equal(resolve(project,'doing',{},[q('waiting-busy')],ctx).tone,'observe');
});
test('running is not a request to launch again',()=>{
  assert.equal(resolve(project,'review',{},[q('running')],ctx).target,'results');
  assert.equal(resolve(project,'doing',{},[],ctx).title,'Проверьте фактический запуск');
});
test('queued guidance honors missing, exhausted and current limits',()=>{
  assert.equal(resolve(project,'sprint',{},[q('queued')],{now}).title,'Сначала проверьте лимит');
  assert.equal(resolve(project,'sprint',{},[q('queued')],{now,budget:{isLive:true,fiveHour:{remainingPercent:0},weekly:{remainingPercent:30}}}).title,'Дождитесь сброса лимита');
  assert.equal(resolve(project,'sprint',{},[q('queued')],ctx).target,'launch');
});
test('old failed attempts do not become current blockers',()=>{
  assert.equal(resolve(project,'review',{},[q('failed',{createdAt:'2026-09-01T00:00:00Z'})],ctx).title,'Примите результат');
  assert.equal(resolve(project,'review',{},[q('failed')],ctx).title,'Разберите последний запуск');
});
test('loading, stale data, due dates and missing steps have meaningful fallbacks',()=>{
  assert.equal(resolve(project,'sprint',{},[],{loaded:false}).target,'refresh');
  assert.equal(resolve(project,'sprint',{},[],{stale:true}).target,'refresh');
  assert.equal(resolve(project,'sprint',{due:'2026-09-01'},[],ctx).title,'Пересогласуйте срок');
  assert.equal(resolve(project,'done',{due:'2026-09-01'},[],ctx).title,'Закрепите результат');
  assert.ok(resolve({id:'two',name:'Новый'},'backlog',{},[],ctx).action);
});
test('history is project-scoped, ordered, and does not invent timestamps',()=>{
  const board={history:[{projectId:'two',at:'2026-09-07',title:'Чужое'},{projectId:'one',at:'2026-09-06',title:'Правка'}]};
  const items=[q('completed',{text:'Задача',createdAt:'2026-09-01',completedAt:'2026-09-05',result:'Готово'}),{...q('failed'),projectId:'two'}];
  const history=entries('one',board,items);
  assert.deepEqual(history.map(e=>e.title),['Правка','Получен результат','Добавлено поручение']);
  assert.equal(entries('three',board,items).length,0);
});
test('completed transition and final result appear once',()=>{
  const item=q('completed',{completedAt:'2026-09-06T09:30:00Z',result:'Проверено',history:[{at:'2026-09-06T09:30:00Z',status:'completed'}]});
  const history=entries('one',{},[item]);
  assert.equal(history.length,2);assert.equal(history[0].text,'Проверено');
});
