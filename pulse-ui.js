/* Read-only event feedback. No queue writes, dispatch, or simulated progress. */
window.PulseUI=(()=>{
  const tracker=MotionEvents.createPulseTracker();
  const labels={queued:'К отправке',dispatching:'Отправляются',running:'В работе',waiting:'Ожидают',stale:'Нет сигнала',done:'Готово',error:'Ошибки'};
  const captions={queued:'Поручения подготовлены',dispatching:'Поручения отправляются',running:'Поручения в работе',waiting:'Поручения ожидают',stale:'Нужна проверка сигнала',done:'Поручения завершены',error:'Поручения завершились с ошибкой или остановлены'};
  let host,notice,returnButton,projects=[],fresh=false,refreshing=false,batch=null;
  const button=kind=>host?.querySelector(`[data-execution-filter="${kind}"]`);
  const canPresent=()=>{
    if(!host||!fresh||refreshing||document.hidden||document.querySelector('dialog[open]'))return false;
    const r=host.getBoundingClientRect();
    return r.width>0&&r.top>=0&&r.bottom<=innerHeight&&r.left>=0&&r.right<=innerWidth;
  };
  function pendingBadge(){
    if(!returnButton)return;
    returnButton.hidden=!tracker.size||canPresent()||Boolean(document.querySelector('dialog[open]'));
    returnButton.textContent=`↑ Пульс: новых событий — ${tracker.size}`;
  }
  function describe(events){
    return [...new Set(events.map(e=>e.to))].map(kind=>{
      const matches=events.filter(e=>e.to===kind);
      const names=[...new Set(matches.map(e=>projects.find(p=>p.id===e.projectId)?.name||'Проект'))];
      return `${captions[kind]} (${matches.length}): ${names.slice(0,2).join(', ')}${names.length>2?` и ещё ${names.length-2}`:''}`;
    }).join(' · ');
  }
  function clearEffects(play){
    for(const timer of play.timers)clearTimeout(timer);
    for(const animation of play.animations)animation.cancel();
    for(const node of play.nodes)node.remove();
  }
  function pause(){
    if(batch){const interrupted=batch;batch=null;clearEffects(interrupted);tracker.putBack(interrupted.events);}
    pendingBadge();
  }
  function effect(play,node,frames,options){
    const animation=window.BoardMotion?.animate(node,frames,options);
    if(animation)play.animations.push(animation);
    return animation;
  }
  function later(play,fn,ms){play.timers.push(setTimeout(()=>{if(batch===play)fn();},ms));}
  function arrival(play,target,kind,delay){
    const ring=document.createElement('i');ring.className='pulse-arrival';ring.setAttribute('aria-hidden','true');
    target.append(ring);play.nodes.push(ring);
    effect(play,ring,[{opacity:0,transform:'scale(.99)'},{opacity:.9,transform:'scale(1)',offset:.45},{opacity:0,transform:'scale(1.025)'}],{duration:1800,iterations:['done','error'].includes(kind)?2:1,delay,easing:'ease-in-out'});
  }
  function travel(play,event,target,delay){
    const source=button(event.from);
    if(!source||source===target)return 0;
    const from=source.getBoundingClientRect(),to=target.getBoundingClientRect();
    const light=document.createElement('i');light.className=`pulse-traveller state-${event.to}`;light.setAttribute('aria-hidden','true');
    Object.assign(light.style,{left:`${from.left+from.width/2-4}px`,top:`${from.bottom-5}px`});
    document.body.append(light);play.nodes.push(light);
    const x=to.left+to.width/2-from.left-from.width/2,y=to.bottom-from.bottom;
    effect(play,light,[{opacity:0,transform:'translate(0,0) scale(.7)'},{opacity:.85,transform:`translate(${x*.4}px,${y*.4-12}px) scale(1)`,offset:.45},{opacity:0,transform:`translate(${x}px,${y}px) scale(.7)`}],{duration:650,delay,easing:'cubic-bezier(.4,0,.2,1)'});
    return 650;
  }
  function flush(){
    pendingBadge();
    if(batch||!tracker.size||!canPresent())return;
    const events=tracker.take().filter(e=>labels[e.to]&&button(e.to));
    if(!events.length)return;
    const clock=new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'});
    notice.textContent=`${clock} · ${describe(events)}`;notice.hidden=false;
    notice.dataset.outcome=events.some(e=>e.to==='error')?'error':events.some(e=>e.to==='done')?'done':'activity';
    if(!window.BoardMotion?.enabled()){pendingBadge();return;}
    const play={events,timers:[],animations:[],nodes:[]};batch=play;
    // One arrival per destination, even when several tasks finish together.
    const destinations=[...new Set(events.map(e=>e.to))];let duration=0;
    destinations.forEach((kind,index)=>{
      const event=events.find(e=>e.to===kind),target=button(kind),delay=index*90;
      const arrivalAt=delay+travel(play,event,target,delay);
      arrival(play,target,kind,arrivalAt);
      duration=Math.max(duration,arrivalAt+(['done','error'].includes(kind)?3600:1800));
    });
    later(play,()=>{clearEffects(play);batch=null;flush();},duration+30);
  }
  function reconcile(){if(!canPresent())pause();else flush();}
  function update(queue,knownProjects,groups,context){
    host=document.getElementById('execution-summary');if(!host)return;
    notice=document.getElementById('pulse-update');returnButton=document.getElementById('pulse-return');
    projects=knownProjects;fresh=ExecutionStatus.fresh(context);
    const entries=queue.map(q=>({id:q.id,projectId:q.projectId,kind:ExecutionStatus.item(q,context).kind}));
    tracker.observe(entries,fresh);
    for(const kind of Object.keys(labels)){
      const metric=button(kind);if(!metric)continue;
      const active=fresh&&['running','dispatching'].includes(kind)&&groups[kind]?.length>0;
      metric.classList.toggle('is-pulse-active',active);
      metric.title=active?'Есть подтверждённые активные поручения. Нажмите, чтобы увидеть проекты.':'Нажмите, чтобы увидеть проекты этого состояния.';
    }
    // Do not keep an old green/red arrival playing after a newer state is known.
    if(batch&&fresh&&batch.events.some(event=>entries.find(e=>e.id===event.id)?.kind!==event.to))pause();
    reconcile();
  }
  document.addEventListener('DOMContentLoaded',()=>{
    host=document.getElementById('execution-summary');if(!host)return;
    notice=document.getElementById('pulse-update');returnButton=document.getElementById('pulse-return');
    returnButton?.addEventListener('click',()=>host.closest('section').scrollIntoView({block:'start',behavior:window.BoardMotion?.enabled()?'smooth':'instant'}));
    new IntersectionObserver(reconcile,{threshold:[0,1]}).observe(host);
    const dialogs=new MutationObserver(reconcile);document.querySelectorAll('dialog').forEach(d=>dialogs.observe(d,{attributes:true,attributeFilter:['open']}));
    new MutationObserver(()=>{if(!window.BoardMotion?.enabled())pause();reconcile();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-motion','data-keyboard']});
    window.addEventListener('resize',()=>{pause();reconcile();});
    // Scrolling invalidates the fixed-position light's endpoints.
    window.addEventListener('scroll',()=>{pause();reconcile();},{passive:true});
  });
  document.addEventListener('visibilitychange',()=>{
    if(document.hidden){pause();return;}
    refreshing=true;
    // Refresh actual state before acknowledging events accumulated out of sight.
    Promise.resolve(typeof loadState==='function'?loadState({quiet:true}):undefined)
      .catch(()=>{}).finally(()=>{refreshing=false;reconcile();});
  });
  return {update};
})();
