/* Disposable UI fixture: no networking, no app.js, no real queue. */
const state={projects:[{id:'sample',name:'Тестовый проект'}],queue:[{id:'sample-task',projectId:'sample',status:'queued'}],lastLoadedAt:Date.now(),executionLoadError:null,board:{}};
window.BoardUI={render:()=>ExecutionView.summary(),filterExecution:kind=>ExecutionView.summary(kind)};
function loadState(){state.lastLoadedAt=Date.now();BoardUI.render();}
function previewStatus(status){
  state.queue[0]={...state.queue[0],status:status==='stale'?'running':status,lastEventAt:new Date(Date.now()-(status==='stale'?180000:0)).toISOString()};
  document.getElementById('preview-state').textContent=`Тестовый статус: ${status}`;loadState();
}
document.querySelectorAll('[data-test-state]').forEach(b=>b.addEventListener('click',()=>previewStatus(b.dataset.testState)));
document.getElementById('test-repeat').addEventListener('click',loadState);
document.getElementById('test-later').addEventListener('click',()=>{document.getElementById('preview-state').textContent='Тестовое завершение появится через 4 секунды';setTimeout(()=>previewStatus('completed'),4000);});
document.getElementById('test-dialog').addEventListener('click',()=>document.getElementById('preview-dialog').showModal());
document.getElementById('test-close').addEventListener('click',()=>document.getElementById('preview-dialog').close());
loadState();
