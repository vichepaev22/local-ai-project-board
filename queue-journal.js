/* Pure journal views. Archiving is filing, not completion or a new dispatch. */
const QueueJournal=(()=>{
  const canArchive=q=>!q.archivedAt&&['completed','failed','interrupted'].includes(q.status);
  const section=q=>q.archivedAt?'archive':q.status==='completed'?'done':'current';
  const dateValue=q=>q.completedAt||q.lastEventAt||q.createdAt||'';
  function dayKey(q){const d=new Date(dateValue(q));return Number.isNaN(d.getTime())?'':`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;}
  function view(items,{tab='current',project='',status='',from='',to=''}={}){
    return items.filter(q=>section(q)===tab&&(!project||q.projectId===project)&&(!status||q.status===status)
      &&(!from||dayKey(q)>=from)&&(!to||(dayKey(q)&&dayKey(q)<=to)))
      .sort((a,b)=>(Date.parse(dateValue(b))||0)-(Date.parse(dateValue(a))||0)||String(a.id).localeCompare(String(b.id)));
  }
  function selection(items,ids,mode,sendable=new Set()){
    return items.filter(q=>ids.has(q.id)&&(mode==='restore'?!!q.archivedAt:mode==='archive'?canArchive(q):mode==='send'?!q.archivedAt&&q.status==='queued'&&sendable.has(q.id):false)).map(q=>q.id);
  }
  return{canArchive,section,dateValue,dayKey,view,selection};
})();
if(typeof module!=='undefined')module.exports=QueueJournal;
