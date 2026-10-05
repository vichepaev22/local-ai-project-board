/* Visual feedback only. Never sends requests or changes project/queue status. */
window.BoardMotion = (() => {
  const easing='cubic-bezier(.22,1,.36,1)', media=matchMedia('(prefers-reduced-motion: reduce)');
  const running=new Set(), effects=new WeakMap(); let quiet=false, keyboard=false, sourceId=null, spotlightTimer, previousQueue=null;
  try { quiet=localStorage.getItem('portfolio-motion')==='quiet'; } catch {}
  const enabled=()=>!quiet&&!media.matches&&!keyboard&&!document.hidden;
  function sync(){document.documentElement.dataset.motion=quiet||media.matches?'quiet':'full';const b=document.getElementById('motion-toggle');if(b){b.setAttribute('aria-pressed',String(!quiet));b.textContent=quiet?'Эффекты: выкл.':'Эффекты: вкл.';}}
  function animate(node,frames,options={}){
    if(!node||!enabled()||!node.animate)return null;
    effects.get(node)?.cancel();
    const a=node.animate(frames,{duration:260,easing,...options});effects.set(node,a);running.add(a);
    a.finished.catch(()=>{}).finally(()=>running.delete(a));return a;
  }
  const card=id=>document.querySelector(`.scrum-board [data-project-id="${CSS.escape(id)}"]`);
  function visible(node){if(!node)return false;const r=node.getBoundingClientRect(),board=document.querySelector('.scrum-board')?.getBoundingClientRect();return r.width>0&&r.bottom>0&&r.top<innerHeight&&r.right>0&&r.left<innerWidth&&(!board||(r.bottom>board.top&&r.top<board.bottom&&r.right>board.left&&r.left<board.right));}
  function enter(dialog,id){
    sourceId=id;dialog.classList.add('motion-managed');
    const origin=card(id);if(!enabled()||!visible(origin))return;
    const from=origin.getBoundingClientRect(),to=dialog.getBoundingClientRect();
    animate(dialog,[{transformOrigin:'0 0',transform:`translate(${from.left-to.left}px,${from.top-to.top}px) scale(${from.width/to.width},${Math.min(1,from.height/to.height)})`,opacity:.45},{transformOrigin:'0 0',transform:'none',opacity:1}],{duration:290});
  }
  function exit(dialog,finish){
    const origin=card(sourceId);sourceId=null;
    if(!enabled()){effects.get(dialog)?.cancel();finish();return;}
    const from=dialog.getBoundingClientRect(),to=visible(origin)?origin.getBoundingClientRect():null;
    const end=to?`translate(${to.left-from.left}px,${to.top-from.top}px) scale(${to.width/from.width},${Math.min(1,to.height/from.height)})`:'translateY(8px) scale(.985)';
    const a=animate(dialog,[{transformOrigin:'0 0',transform:getComputedStyle(dialog).transform,opacity:1},{transformOrigin:'0 0',transform:end,opacity:0}],{duration:180});
    if(a)a.finished.catch(()=>{}).finally(finish);else finish();
  }
  function positions(){return new Map([...document.querySelectorAll('.scrum-board .project-card')].map(n=>[n.dataset.projectId,n.getBoundingClientRect()]));}
  function flip(before){if(!enabled())return;for(const [id,r] of before){const n=card(id);if(!n||!visible(n))continue;const end=n.getBoundingClientRect(),x=r.left-end.left,y=r.top-end.top;if(Math.abs(x)+Math.abs(y)>1)animate(n,[{transform:`translate(${x}px,${y}px)`},{transform:'none'}]);}}
  function glow(node,kind='result'){if(!node)return;node.classList.remove('motion-result','motion-land','motion-accepted');if(!enabled())return;node.classList.add(`motion-${kind}`);setTimeout(()=>node.classList.remove(`motion-${kind}`),1100);}
  function beam(from,to,delay=0){
    if(!enabled())return;
    const x=to.x-from.x,y=to.y-from.y,line=document.createElement('i');line.className='launch-beam';line.setAttribute('aria-hidden','true');
    Object.assign(line.style,{left:`${from.x}px`,top:`${from.y}px`,width:`${Math.hypot(x,y)}px`,rotate:`${Math.atan2(y,x)}rad`});document.body.append(line);
    const a=animate(line,[{transform:'scaleX(0)',opacity:0},{transform:'scaleX(1)',opacity:.7,offset:.6},{transform:'scaleX(1)',opacity:0}],{duration:650,delay});
    if(a)a.finished.catch(()=>{}).finally(()=>line.remove());else line.remove();
  }
  function launch(ids){
    if(!enabled())return;
    const origin=document.getElementById('launch-button')?.getBoundingClientRect();if(!origin)return;
    [...new Set(ids)].forEach((id,index)=>{const n=card(id);if(!visible(n))return;const r=n.getBoundingClientRect();beam({x:origin.left+origin.width/2,y:origin.bottom},{x:r.left+r.width/2,y:r.top+20},index*70);setTimeout(()=>glow(card(id),'land'),250+index*70);});
  }
  document.addEventListener('pointerdown',()=>{keyboard=false;delete document.documentElement.dataset.keyboard;},true);
  document.addEventListener('keydown',()=>{keyboard=true;document.documentElement.dataset.keyboard='true';},true);
  function stop(){for(const a of running)a.cancel();document.querySelectorAll('.launch-beam').forEach(n=>n.remove());}
  media.addEventListener('change',()=>{sync();if(media.matches)stop();});
  document.addEventListener('visibilitychange',()=>{document.documentElement.classList.toggle('motion-paused',document.hidden);if(document.hidden)stop();});
  document.addEventListener('DOMContentLoaded',()=>{sync();document.getElementById('motion-toggle')?.addEventListener('click',()=>{quiet=!quiet;try{localStorage.setItem('portfolio-motion',quiet?'quiet':'full');}catch{}sync();if(quiet)stop();});});
  sync();
  function spotlight(id){
    const n=card(id);if(!n)return;clearTimeout(spotlightTimer);const board=n.closest('.scrum-board');board.querySelectorAll('.is-spotlit').forEach(el=>el.classList.remove('is-spotlit'));
    n.scrollIntoView({block:'nearest',inline:'center',behavior:enabled()?'smooth':'instant'});n.querySelector('.attention-radar')?.focus({preventScroll:true});n.classList.add('is-spotlit');board.classList.add('has-spotlight');
    spotlightTimer=setTimeout(()=>{board.classList.remove('has-spotlight');n.classList.remove('is-spotlit');},3200);
  }
  function focusNode(node){if(enabled()&&node){node.classList.add('motion-focus');setTimeout(()=>node.classList.remove('motion-focus'),1200);}}
  function observe(queue){
    for(const event of MotionEvents.diff(previousQueue,queue)){const n=card(event.projectId);if(event.kind==='result')glow(n);else if(event.kind==='signal'){if(n?.dataset.execution==='running'&&enabled()&&!n.classList.contains('signal-flash')){n.classList.add('signal-flash');setTimeout(()=>n.classList.remove('signal-flash'),750);}}else{const radar=n?.querySelector('.attention-radar');if(radar&&enabled()){radar.classList.remove('radar-arriving');requestAnimationFrame(()=>radar.classList.add('radar-arriving'));}}}
    previousQueue=new Map(queue.map(q=>[q.id,{status:q.status,isStale:q.isStale,lastEventAt:q.lastEventAt}]));
  }
  function historyReveal(container){if(!enabled())return;[...container.children].slice(0,6).forEach((n,i)=>animate(n,[{opacity:.3,transform:'translateY(10px)'},{opacity:1,transform:'none'}],{duration:220,delay:i*35}));}
  return{enabled,animate,card,visible,enter,exit,positions,flip,glow,beam,launch,spotlight,focusNode,observe,historyReveal};
})();
