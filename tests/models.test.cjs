const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const Models=fs.existsSync(require('node:path').join(__dirname,'../task-models.js'))?require('../task-models.js'):{};

test('model options preserve unavailable draft choices instead of silently resetting',()=>{
  assert.equal(typeof Models.options,'function');
  const options=Models.options([{id:'fast',label:'Fast'}],'removed');
  assert.equal(options[0].value,'');
  assert.ok(options.some(o=>o.value==='fast'));
  assert.ok(options.some(o=>o.value==='removed' && o.unavailable));
});
test('saved queue model label does not depend on a later catalog change',()=>{
  assert.equal(typeof Models.label,'function');
  assert.equal(Models.label({model:'fast',modelLabel:'Fast Model'}),'Fast Model');
  assert.equal(Models.label({model:'removed'}),'removed');
  assert.equal(Models.label({}),'Как в задаче');
});
test('known model has one option and default is never counted as unavailable',()=>{
  assert.equal(typeof Models.options,'function');
  assert.equal(Models.options([{id:'fast',label:'Fast'}],'fast').length,2);
  assert.equal(Models.options([],'').filter(o=>o.unavailable).length,0);
});

function pickerFixture(fetchModels) {
  const context={document:{createElement:()=>({})},module:{exports:{}}};
  require('node:vm').runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../task-models.js'),'utf8'),context);
  const select={value:'',listeners:{},replaceChildren(...rows){this.rows=rows;this.value=rows[0]?.value||'';},setCustomValidity(v){this.error=v;},setAttribute(){},addEventListener(name,fn){this.listeners[name]=fn;}};
  const status={},reload={addEventListener(){}},changes=[];
  const picker=context.module.exports.create({select,status,reload,fetchModels,onChange:()=>changes.push(select.value)});
  return {picker,select,status,reload,changes};
}
test('catalog response preserves the choice of a card opened while it was loading',async()=>{
  let finish;const f=pickerFixture(()=>new Promise(resolve=>{finish=resolve;}));
  f.picker.setValue('fast');const load=f.picker.load();
  f.picker.setValue('deep');
  finish({models:[{id:'fast',label:'Fast'},{id:'deep',label:'Deep'}]});await load;
  assert.equal(f.select.value,'deep');assert.equal(f.select.error,'');
  assert.deepEqual(f.changes,[]);
});
test('catalog failure preserves selection and explicit default remains usable',async()=>{
  const f=pickerFixture(async()=>{throw new Error('offline');});
  f.picker.setValue('fast');await f.picker.load();
  assert.equal(f.select.value,'fast');assert.ok(f.select.error);assert.match(f.status.textContent,/offline/);
  f.select.value='';f.select.listeners.change();
  assert.equal(f.select.error,'');assert.deepEqual(f.changes,['']);
});
test('removed model remains visible but cannot be submitted until user chooses another',async()=>{
  const f=pickerFixture(async()=>({models:[{id:'fast',label:'Fast'}]}));
  f.picker.setValue('removed');await f.picker.load();
  assert.equal(f.select.value,'removed');assert.ok(f.select.error);
  f.select.value='fast';f.select.listeners.change();
  assert.equal(f.select.error,'');assert.deepEqual(f.changes,['fast']);
});
