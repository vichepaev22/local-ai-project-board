/* Pointer events provide the same drag gesture for a mouse, touch and pen. */
window.BoardDrag = (()=>{
  let drag=null,suppressUntil=0,frame=0;
  function begin(event,node,id){
    if(event.button!==0||BoardUI.saving||drag)return;
    event.preventDefault();
    const r=node.getBoundingClientRect();
    drag={id,node,pointer:event.pointerId,x:event.clientX,y:event.clientY,lastX:event.clientX,lastY:event.clientY,px:r.left,py:r.top,dx:event.clientX-r.left,dy:event.clientY-r.top,width:r.width,ghost:null,slot:null,target:null,before:null};
    (event.target.closest(".card-open,.card-grip") || event.currentTarget).setPointerCapture(event.pointerId);
  }
  function clearMarks(){document.querySelectorAll('.is-drop-target').forEach(n=>n.classList.remove('is-drop-target'));}
  function targetAt(x,y){
    if(!drag)return;const target=document.elementFromPoint(x,y)?.closest('.board-column');
    const before=target?[...target.querySelectorAll('.project-card')].find(n=>n!==drag.node&&y<n.getBoundingClientRect().top+n.getBoundingClientRect().height/2):null;
    const id=target?.dataset.column||null,next=before?.dataset.projectId||null;
    if(id===drag.target&&next===drag.before)return;
    const positions=BoardMotion.positions();clearMarks();drag.target=id;drag.before=next;
    if(target){target.classList.add('is-drop-target');target.querySelector('.column-cards').insertBefore(drag.slot,before);}else drag.slot.remove();
    BoardMotion.flip(positions);
  }
  function tick(){
    if(!drag?.ghost){frame=0;return;}const d=drag,x=d.lastX-d.dx,y=d.lastY-d.dy,factor=BoardMotion.enabled()?.42:1;
    const tilt=BoardMotion.enabled()?Math.max(-4,Math.min(4,(x-d.px)*.13)):0;
    d.px+=(x-d.px)*factor;d.py+=(y-d.py)*factor;
    d.ghost.style.transform=`translate3d(${d.px}px,${d.py}px,0) rotate(${tilt}deg) scale(1.025)`;
    const board=d.node.closest('.scrum-board'),r=board.getBoundingClientRect();
    if(d.lastX>r.right-40)board.scrollLeft+=12;else if(d.lastX<r.left+40)board.scrollLeft-=12;
    if(d.lastY>r.bottom-40)board.scrollTop+=9;else if(d.lastY<r.top+40)board.scrollTop-=9;
    targetAt(d.lastX,d.lastY);frame=requestAnimationFrame(tick);
  }
  function move(e){
    if(!drag||e.pointerId!==drag.pointer)return;
    if(!drag.ghost&&Math.hypot(e.clientX-drag.x,e.clientY-drag.y)<5)return;
    e.preventDefault();
    drag.lastX=e.clientX;drag.lastY=e.clientY;
    if(!drag.ghost){drag.ghost=drag.node.cloneNode(true);drag.ghost.classList.add('drag-ghost');drag.ghost.removeAttribute('data-project-id');drag.ghost.setAttribute('aria-hidden','true');drag.ghost.inert=true;drag.ghost.style.width=`${drag.width}px`;document.body.append(drag.ghost);drag.slot=document.createElement('div');drag.slot.className='drag-slot';drag.slot.textContent='Отпустите здесь';drag.slot.setAttribute('aria-hidden','true');drag.node.classList.add('is-dragging');document.body.classList.add('is-dragging');frame=requestAnimationFrame(tick);}
  }
  function finish(cancel=false){
    if(!drag)return;const d=drag;drag=null;cancelAnimationFrame(frame);frame=0;d.slot?.remove();d.ghost?.remove();d.node.classList.remove("is-dragging");document.body.classList.remove("is-dragging");clearMarks();
    if(d.ghost)suppressUntil=Date.now()+300;
    if(!cancel&&d.ghost&&d.target)BoardUI.move(d.id,d.target,d.before);
  }
  document.addEventListener("pointermove",move,{passive:false});document.addEventListener("pointerup",e=>{if(e.pointerId===drag?.pointer)finish();});document.addEventListener("pointercancel",e=>{if(e.pointerId===drag?.pointer)finish(true);});window.addEventListener("blur",()=>finish(true));document.addEventListener("keydown",e=>{if(e.key==="Escape"&&drag){e.preventDefault();finish(true);}});
  return {begin,get active(){return !!drag;},get ignoreClick(){return Date.now()<suppressUntil;}};
})();
