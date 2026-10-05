/* Pure diff: initial/historical results and repeated polls never cause celebrations. */
const MotionEvents={
  createPulseTracker(){
    let previous=null;
    const pending=new Map();
    return {
      observe(entries,fresh=true){
        if(!fresh)return;
        if(previous)for(const entry of entries){
          const old=previous.get(entry.id);
          if(old?.kind===entry.kind)continue;
          const unseen=pending.get(entry.id);
          pending.set(entry.id,{id:entry.id,projectId:entry.projectId,from:unseen?unseen.from:old?.kind||null,to:entry.kind});
        }
        previous=new Map(entries.map(entry=>[entry.id,{...entry}]));
      },
      take(){const events=[...pending.values()];pending.clear();return events;},
      putBack(events){for(const event of events)if(!pending.has(event.id))pending.set(event.id,event);},
      get size(){return pending.size;},
    };
  },
  diff(previous,queue){
    const events=[];
    for(const q of queue){const old=previous?.get(q.id);if(!old)continue;
      if(q.status==='completed'&&old.status!=='completed')events.push({projectId:q.projectId,kind:'result'});
      if(q.status==='running'&&!q.isStale&&q.lastEventAt&&old.lastEventAt&&q.lastEventAt!==old.lastEventAt)events.push({projectId:q.projectId,kind:'signal'});
      if((q.status==='waiting-user'&&old.status!=='waiting-user')||(q.isStale&&!old.isStale))events.push({projectId:q.projectId,kind:'attention'});
    }return events;
  },
};
if(typeof module!=='undefined')module.exports=MotionEvents;
