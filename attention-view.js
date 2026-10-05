window.AttentionView = (() => {
  const get = project => {
    const hint=Attention.resolve(project, BoardUI.locationOf(project.id)?.id, BoardUI.meta(project.id), state.queue, {
    budget:state.budget, loaded:!!state.lastLoadedAt, stale:!!state.executionLoadError || (!!state.lastLoadedAt && Date.now()-state.lastLoadedAt>90000),
    });
    const execution=ExecutionView.describe(project.id);
    return execution.kind==='error'&&hint.target==='results'?{...hint,action:execution.detail}:hint;
  };
  function radar(hint, compact=false) {
    const {el} = BoardUI, box=el(compact?"button":"div",`attention-radar${compact?" is-compact":""}`);
    box.dataset.tone=hint.tone;
    const head=el("span","radar-heading"), orbit=el("i","radar-orbit"); orbit.setAttribute("aria-hidden","true");
    head.append(orbit,el("span","","ВАШ ФОКУС"),el("span","radar-code",hint.tone==="observe"?"НАБЛЮДАТЬ":"СЛЕДУЮЩИЙ ХОД"));
    box.append(head,el(compact?"strong":"h3","radar-title",hint.title),el("span","radar-action",hint.action));
    if(!compact) box.append(el("small","radar-source",`${hint.source} · Подсказка по данным доски, без вызова AI`));
    return box;
  }
  function card(project) {
    const node=radar(get(project),true);
    node.setAttribute("aria-label",`Ваш фокус: ${BoardUI.name(project)}`);
    node.addEventListener("click",()=>ProjectDetail.open(project.id,false,"attention"));
    return node;
  }
  function detail(project) {
    const hint=get(project), container=document.getElementById("detail-attention");
    const key=JSON.stringify(hint); if(container.dataset.fingerprint===key)return; container.dataset.fingerprint=key;
    const box=radar(hint), button=BoardUI.el("button","radar-button",({task:"Взять подсказку в поручение ↗",results:"Посмотреть поручения и результат ↗",launch:"Проверить очередь ↗",refresh:"Обновить состояние ↻"})[hint.target]);
    button.addEventListener("click",()=>{
      if(hint.target==="task") ProjectDetail.useHint(hint.prompt);
      else if(hint.target==="results") ProjectDetail.jump("results");
      else if(hint.target==="launch") BoardUI.open("launch-dialog");
      else loadState();
    });
    box.append(button); container.replaceChildren(box);if(BoardMotion.enabled())box.classList.add('radar-arriving');
  }
  document.addEventListener('DOMContentLoaded',()=>document.getElementById('attention-spotlight')?.addEventListener('click',()=>{
    const score=p=>(['attention','error'].includes(BoardUI.status(p.id).tone)?100:0)+(get(p).tone==='decision'?20:get(p).tone==='check'?30:0)+(BoardUI.meta(p.id).urgent?10:0)+(BoardUI.meta(p.id).important?5:0);
    const p=[...state.projects].sort((a,b)=>score(b)-score(a))[0];if(!p)return;BoardUI.reveal(p.id);BoardUI.toast(`${BoardUI.name(p)}: ${get(p).title}`);
  }));
  return {get,card,detail};
})();
