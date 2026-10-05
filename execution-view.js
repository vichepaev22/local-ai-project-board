/* DOM presentation only. No dispatch, writes or invented progress. */
window.ExecutionView = (() => {
  const definitions=[['running','В работе','◉'],['dispatching','Отправляются','↗'],['waiting','Ожидают','Ⅱ'],['stale','Нет сигнала','?'],['error','Ошибки','!'],['queued','К отправке','◇'],['done','Готово','✓']];
  const make=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const context=()=>({now:Date.now(),lastLoadedAt:state.lastLoadedAt,loadError:state.executionLoadError});
  function describe(id){return ExecutionStatus.project(id,state.queue,context());}
  function card(project,s) {
    const area=make('section','execution-card');area.setAttribute('aria-label',`Выполнение: ${BoardUI.name(project)}`);
    const badges=make('div','execution-badges');
    const entries=s.entries.length?s.entries:[s], seen=new Set();
    for(const entry of entries){if(seen.has(entry.kind))continue;seen.add(entry.kind);const badge=make('span',`execution-badge state-${entry.kind}`,entry.label);badges.append(badge);}
    area.append(badges);
    if(s.item){
      const q=s.item;
      if(s.detail)area.append(make('p','execution-action',`${['running','dispatching','done'].includes(s.kind)?'Последнее действие: ':''}${s.detail}`));
      const signal=q.lastEventAt || q.completedAt || q.startedAt;
      const stamp=make('small','execution-signal',ExecutionStatus.relative(signal,Date.now()));stamp.dataset.signalAt=signal || '';stamp.title=formatAt(signal);area.append(stamp);
      const cta=make('button','execution-link',({running:'Ход выполнения →',dispatching:'Проверить отправку →',waiting:q.status==='waiting-user'?'Открыть запрос →':'Что требуется →',stale:'Проверить состояние →',error:'Разобрать ошибку →',done:'Посмотреть результат →',queued:'Проверить поручение →'})[s.kind] || 'Подробнее →');
      cta.type='button';cta.addEventListener('click',()=>ProjectDetail.open(project.id,false,'results'));area.append(cta);
    }
    return area;
  }
  function contour(){const n=make('div','execution-contour');n.setAttribute('aria-hidden','true');for(const edge of ['top','right','bottom','left'])n.append(make('i',`flow-${edge}`));return n;}
  function summary(selected='all') {
    const groups=ExecutionStatus.summary(state.projects,state.queue,context()), host=document.getElementById('execution-summary');if(!host)return;
    if(!host.children.length){for(const [kind,label,icon] of definitions){const b=make('button',`execution-metric state-${kind}`);b.type='button';b.dataset.executionFilter=kind;b.append(make('span','metric-icon',icon),make('span','metric-label',label),make('strong','metric-count','—'));b.addEventListener('click',()=>BoardUI.filterExecution(kind));host.append(b);}}
    for(const b of host.children){const kind=b.dataset.executionFilter,count=state.lastLoadedAt?groups[kind].length:'—';b.querySelector('.metric-count').textContent=count;b.setAttribute('aria-label',`${definitions.find(d=>d[0]===kind)[1]}: проектов — ${count}`);b.setAttribute('aria-pressed',String(selected===kind));}
    const note=document.getElementById('execution-health'), ctx=context();
    const message=!state.lastLoadedAt?'Получаем очередь. Статусы пока не подтверждены.':!ExecutionStatus.fresh(ctx)?'Нет свежего подтверждения от сервера. Движение остановлено; показаны последние известные данные.':'Состояния поручений, не колонки Scrum. Счётчики — по проектам; один проект может иметь несколько состояний.';
    if(note.textContent!==message)note.textContent=message;
    note.classList.toggle('is-warning',!ExecutionStatus.fresh(ctx));
    const reset=document.getElementById('execution-reset');reset.hidden=selected==='all';reset.textContent=selected==='all'?'Показать все проекты':`${definitions.find(d=>d[0]===selected)?.[1]} · Сбросить фильтр ×`;
    window.PulseUI?.update(state.queue,state.projects,groups,ctx);
  }
  function tick(){
    if(typeof state==='undefined'||!state.board)return;
    for(const n of document.querySelectorAll('[data-signal-at]'))n.textContent=ExecutionStatus.relative(n.dataset.signalAt,Date.now());
    // Re-render only at evidence/status boundaries, not on every timer tick.
    BoardUI.render();
  }
  document.addEventListener('DOMContentLoaded',()=>{document.getElementById('execution-reset')?.addEventListener('click',()=>BoardUI.filterExecution('all'));setInterval(()=>{if(!document.hidden&&!window.BoardDrag?.active)tick();},5000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});});
  return {describe,card,contour,summary,context};
})();
