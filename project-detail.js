window.ProjectDetail = (()=>{
  const {$,el}=BoardUI; let current=null,detailFingerprint="",historyFingerprint="",modelPicker=null;
  function draftKey(){return `portfolio-draft:${current}`;}
  function storeDraft(){if(!current)return;try{localStorage.setItem(draftKey(),JSON.stringify({text:$("detail-task").value,kind:$("detail-kind").value,scope:$("detail-scope").value,model:$("detail-model").value}));$("draft-status").textContent="Черновик сохранён на этом устройстве";}catch{$("draft-status").textContent="Черновик только в текущем окне";}}
  function open(id,fromHash=false,section="attention"){
    const p=state.projects.find(p=>p.id===id);if(!p)return;
    if(current && current!==id)storeDraft();
    current=id;detailFingerprint="";historyFingerprint="";const m=BoardUI.meta(id);
    for(const key of ["title","color","due","notes"])$("card-"+key).value=m[key]|| (key==="color"?"paper":"");
    $("card-important").checked=!!m.important;$("card-urgent").checked=!!m.urgent;$("card-discussion").value=m.discussionUrl||"";
    $("detail-workspace").value=p.workspace||'';
    $("detail-task").value="";$("detail-kind").value="next-step";$("detail-scope").value="normal";
    modelPicker.setValue();
    try{const draft=JSON.parse(localStorage.getItem(draftKey())||"null");if(draft){$("detail-task").value=draft.text||"";$("detail-kind").value=draft.kind||"next-step";$("detail-scope").value=draft.scope||"normal";modelPicker.setValue(draft.model);}}catch{}
    modelPicker.load();
    refresh();BoardUI.open("project-dialog");
    if(section!=="attention")jump(section);else $("project-dialog").scrollTop=0;
    if(!fromHash&&section==='attention')window.BoardMotion?.enter($("project-dialog"),id);
    if(!fromHash&&location.hash!==`#project/${id}`)history.pushState({project:id},"",`#project/${id}`);
  }
  function onClose(){
    const previous=current;
    if(current)storeDraft();current=null;
    if(location.hash.startsWith("#project/"))history.replaceState(null,"",location.pathname+location.search);
    if(previous)document.querySelector(`[data-project-id="${CSS.escape(previous)}"] .card-open`)?.focus({preventScroll:true});
  }
  function refresh(){
    if(!current)return;const p=state.projects.find(p=>p.id===current);if(!p)return;
    const m=BoardUI.meta(current),s=BoardUI.status(current),col=BoardUI.locationOf(current);
    $("detail-title").textContent=BoardUI.name(p);$("detail-monogram").textContent=BoardUI.mono(current);$("project-cover").dataset.color=m.color||"paper";
    $("detail-stage").textContent=p.stage;$("detail-goal").textContent=p.goal;$("detail-steps").replaceChildren(...p.nextSteps.map(s=>el("li","",s)));
    $("detail-column-label").textContent=col.name;BoardUI.columns($("detail-column"),col.id);
    $("detail-lamp").replaceChildren(BoardUI.lamp(s.tone));$("detail-lamp").title=s.text;
    $("move-up").disabled=col.cards.indexOf(current)===0;$("move-down").disabled=col.cards.indexOf(current)===col.cards.length-1;
    $("detail-route").textContent=p.route.label;const route=$("detail-codex-link");route.hidden=!p.route.threadId;
    if(p.route.threadId)route.href=`codex://threads/${encodeURIComponent(p.route.threadId)}`;
    BoardUI.link($("detail-discussion-link"),m.discussionUrl||state.board.discussionUrl);
    AttentionView.detail(p);
    const events=ProjectHistory.entries(current,state.board,state.queue),historyKey=JSON.stringify(events);
    if(historyKey!==historyFingerprint){historyFingerprint=historyKey;ProjectHistory.render($("detail-history"),events);$("history-count").textContent=events.length;}
    const items=state.queue.filter(q=>q.projectId===current).slice().reverse(),key=JSON.stringify(items);
    if(key!==detailFingerprint){detailFingerprint=key;$("detail-queue").replaceChildren(...(items.length?items.map(q=>{const row=createQueueItem(q);row.querySelector("input")?.remove();return row;}):[createEmptyState("Добавьте первое поручение для следующего шага.")]));}
  }
  async function shift(delta){const col=BoardUI.locationOf(current),index=col.cards.indexOf(current),before=delta<0?col.cards[index-1]:col.cards[index+2]||null;await BoardUI.move(current,col.id,before);}
  function jump(section){
    const target=$(({task:"detail-task",history:"project-history",results:"project-results",overview:"project-overview",attention:"detail-attention"})[section]);
    if(!target)return;target.scrollIntoView({block:"start",behavior:"instant"});target.focus({preventScroll:true});window.BoardMotion?.focusNode(target);
    if(section==='history')window.BoardMotion?.historyReveal($('detail-history'));
  }
  function useHint(text){
    const field=$("detail-task"),existing=field.value.trim();
    if(existing.includes(text)){jump("task");return;}
    const combined=existing?`${existing}\n\nПодсказка:\n${text}`:text;
    if(combined.length>field.maxLength){BoardUI.toast("В черновике недостаточно места. Сократите его, затем добавьте подсказку.",true);return;}
    field.value=combined;storeDraft();jump("task");BoardUI.toast("Подсказка в черновике. Проверьте текст — ничего ещё не отправлено.");
  }
  document.addEventListener("DOMContentLoaded",()=>{
    modelPicker=TaskModels.create({select:$("detail-model"),status:$("model-status"),reload:$("reload-models"),fetchModels:()=>request('/api/models'),onChange:storeDraft});
    document.querySelectorAll("[data-detail-section]").forEach(b=>b.addEventListener("click",()=>jump(b.dataset.detailSection)));
    ["detail-task","detail-kind","detail-scope"].forEach(id=>$(id).addEventListener("input",storeDraft));
    $("detail-task-form").addEventListener("submit",async e=>{
      e.preventDefault();const text=$("detail-task").value.trim();if(!text)return;
      const id=current;$("charge-button").disabled=true;
      try{const ok=await queueUpdates([{projectId:id,kind:$("detail-kind").value,scope:$("detail-scope").value,model:$("detail-model").value||null,text}]);if(ok){if(current===id){$("detail-task").value="";storeDraft();}BoardUI.toast("Карточка заряжена. Нажмите «Поехали» на доске, чтобы начать.");}}finally{$("charge-button").disabled=false;}
    });
    $("detail-column").addEventListener("change",e=>BoardUI.move(current,e.target.value));$("move-up").addEventListener("click",()=>shift(-1));$("move-down").addEventListener("click",()=>shift(1));
    $("card-settings-form").addEventListener("submit",async e=>{e.preventDefault();const changes={title:$("card-title").value,color:$("card-color").value,due:$("card-due").value,notes:$("card-notes").value,important:$("card-important").checked,urgent:$("card-urgent").checked,discussionUrl:$("card-discussion").value};if(await BoardUI.save({op:"card",projectId:current,changes}))BoardUI.toast("Карточка сохранена");});
    $("workspace-form").addEventListener('submit',async e=>{e.preventDefault();if(await BoardUI.save({op:'set-workspace',projectId:current,workspace:$("detail-workspace").value}))BoardUI.toast('Рабочая папка сохранена. Поручения не запускались.');});
    $("copy-project").addEventListener("click",()=>BoardUI.copy(BoardUI.brief(state.projects.find(p=>p.id===current))));
    window.addEventListener("popstate",()=>{if(location.hash.startsWith("#project/")){open(decodeURIComponent(location.hash.slice(9)),true);}else if($("project-dialog").open)BoardUI.close($("project-dialog"));});
  });
  function restore(){if(!current&&location.hash.startsWith("#project/"))open(decodeURIComponent(location.hash.slice(9)),true);}
  return{open,onClose,refresh,restore,jump,useHint};
})();
