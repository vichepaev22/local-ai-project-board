const {test}=require('node:test'),assert=require('node:assert/strict'),{diff}=require('../motion-events.js');
const fs=require('node:fs'),path=require('node:path');
test('demo cannot call the live queue and does not load live app code',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../demo.html'),'utf8'),js=fs.readFileSync(path.join(__dirname,'../demo.js'),'utf8');
  assert.match(html,/connect-src 'none'/);assert.doesNotMatch(html,/src="(?:app|board-ui|project-detail)\.js/);
  assert.doesNotMatch(js,/\bfetch\s*\(|XMLHttpRequest|WebSocket|\/api\//);
});
test('initial results and repeated polls are silent',()=>{
  const queue=[{id:'1',projectId:'one',status:'completed'}];assert.deepEqual(diff(null,queue),[]);assert.deepEqual(diff(new Map([['1',queue[0]]]),queue),[]);
});
test('only actual completion generates result signal',()=>{
  const previous=new Map([['1',{status:'running'}]]);
  for(const status of ['queued','failed','interrupted','running'])assert.deepEqual(diff(previous,[{id:'1',status,projectId:'one'}]),[]);
  assert.deepEqual(diff(previous,[{id:'1',status:'completed',projectId:'one'}]),[{projectId:'one',kind:'result'}]);
});
test('new wait and lost heartbeat attract attention once',()=>{
  const previous=new Map([['1',{status:'running',isStale:false}]]);
  assert.equal(diff(previous,[{id:'1',status:'waiting-user',projectId:'one'}])[0].kind,'attention');
  assert.equal(diff(previous,[{id:'1',status:'running',isStale:true,projectId:'one'}])[0].kind,'attention');
  assert.deepEqual(diff(new Map([['1',{status:'running',isStale:true}]]),[{id:'1',status:'running',isStale:true,projectId:'one'}]),[]);
});
