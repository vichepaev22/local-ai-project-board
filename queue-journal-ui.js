/* Journal controls. Archive selection and dispatch selection are intentionally separate. */
window.QueueJournalUI=(()=>{
  const $=id=>document.getElementById(id);
  let tab='current',archiveMode=false,busy=false,rowsKey='',projectKey='';
  const filters={project:'',status:'',from:'',to:''},selected=new Set(),sendChoices=new Map();
  const mode=()=>tab==='archive'?'restore':tab==='done'||archiveMode?'archive':'send';
  const visible=()=>QueueJournal.view(state.queue,{tab,...filters});
  const eligible=items=>QueueJournal.selection(items,new Set(items.map(q=>q.id)),mode(),state.sendableQueueIds);
  function selectedIds(){
    const items=visible(),ids=mode()==='send'?new Set(items.filter(q=>sendChoices.get(q.id)!==false).map(q=>q.id)):selected;
    return QueueJournal.selection(items,ids,mode(),state.sendableQueueIds);
  }
  function syncSelection(){
    const ids=selectedIds(),allowed=eligible(visible()),all=$('journal-select-all');if(!all)return;
    $('journal-selected').textContent=`Выбрано: ${ids.length}`;
    all.checked=allowed.length>0&&ids.length===allowed.length;all.indeterminate=ids.length>0&&ids.length<allowed.length;all.disabled=busy||!allowed.length;
    const action=mode();
    $('journal-archive-selected').hidden=action==='send';
    $('journal-archive-selected').disabled=busy||!ids.length;
    $('journal-archive-selected').lastElementChild.textContent=busy?'Сохраняем…':action==='restore'?'Вернуть выбранные':'В архив выбранные';
    $('journal-selection-note').textContent=action==='send'?'Флажки — только для отправки. Завершённые записи можно убрать кнопкой архива.':action==='archive'?'Флажки — для архива. Можно выбрать завершённые, ошибочные и остановленные поручения.':'Флажки — для возврата в журнал. Восстановление не запускает задачи.';
    $('journal-select-all-label').textContent=action==='send'?'Выбрать доступные к отправке':action==='archive'?'Выбрать доступные для архива':'Выбрать для возврата';
    $('journal-launch-controls').hidden=action!=='send';
    $('confirm-button').disabled=busy||action!=='send'||!ids.length;
  }
  function icon(restore=false){
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
    const path=document.createElementNS(svg.namespaceURI,'path');
    path.setAttribute('d',restore?'M5 8v12h14V8M3 4h18v4H3zM12 16v-5m-3 3 3-3 3 3':'M5 8v12h14V8M3 4h18v4H3zM9 12h6');
    svg.append(path);return svg;
  }
  function archiveButton(item){
    const restore=!!item.archivedAt,b=document.createElement('button');b.type='button';b.className='journal-file-button';
    b.title=restore?'Вернуть запись без повторной отправки':'Убрать из журнала; результат останется в архиве';
    b.setAttribute('aria-label',`${restore?'Вернуть из архива':'В архив'}: ${item.projectName}`);b.append(icon(restore));
    const label=document.createElement('span');label.textContent=restore?'Вернуть':'В архив';b.append(label);b.disabled=busy;
    b.addEventListener('click',()=>file([item.id],!restore));return b;
  }
  function row(item){
    const n=createQueueItem(item,{selection:'none'}),action=mode(),canSelect=eligible([item]).length>0;
    n.dataset.journalId=item.id;
    if(canSelect){
      const input=document.createElement('input');input.type='checkbox';input.dataset.queueId=item.id;input.dataset.queueAction=action;
      input.setAttribute('aria-label',`${action==='send'?'Отправить':action==='archive'?'Архивировать':'Восстановить'} поручение: ${item.projectName}`);
      input.checked=selectedIds().includes(item.id);input.disabled=busy;
      input.addEventListener('change',()=>{if(action==='send')sendChoices.set(item.id,input.checked);else if(input.checked)selected.add(item.id);else selected.delete(item.id);syncSelection();});
      n.prepend(input);
    }
    const tools=document.createElement('div');tools.className='journal-row-tools';
    const date=document.createElement('time');date.dateTime=QueueJournal.dateValue(item);date.textContent=formatAt(date.dateTime);tools.append(date);
    if(item.archivedAt||QueueJournal.canArchive(item))tools.append(archiveButton(item));
    else {
      const explanation=document.createElement('small');explanation.className='journal-eligibility';
      explanation.textContent=item.status==='queued'?(state.sendableQueueIds.has(item.id)?'В архив — после завершения':'Автозапуск недоступен: проверьте режим исполнителя выше'):'В архив — после завершения или остановки';tools.append(explanation);
    }
    n.querySelector('.queue-content').prepend(tools);return n;
  }
  function render(){
    if(!$('journal-tabs'))return;
    const items=visible(),action=mode();
    for(const id of [...selected])if(!items.some(q=>q.id===id))selected.delete(id);
    document.querySelectorAll('[data-journal-tab]').forEach(b=>{
      const active=b.dataset.journalTab===tab;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;
      b.querySelector('span').textContent=state.queue.filter(q=>QueueJournal.section(q)===b.dataset.journalTab).length;
    });
    $('queue-list').setAttribute('aria-labelledby',`journal-tab-${tab}`);
    $('journal-mode').hidden=tab!=='current';$('journal-mode').setAttribute('aria-pressed',String(archiveMode));
    $('journal-mode').textContent=archiveMode?'← К отправке':'Выбрать для архива';$('journal-mode').disabled=busy;
    const projects=[...new Map([...state.projects.map(p=>[p.id,p.name]),...state.queue.filter(q=>q.projectId).map(q=>[q.projectId,q.projectName||q.projectId])]).entries()];
    const pk=JSON.stringify(projects);
    if(pk!==projectKey){projectKey=pk;const select=$('journal-project');select.replaceChildren(new Option('Все проекты',''),...projects.map(([id,name])=>new Option(name,id)));select.value=filters.project;}
    const filterCount=Object.values(filters).filter(Boolean).length;
    $('journal-filter-count').textContent=filterCount?String(filterCount):'';
    $('journal-count').textContent=`Показано ${items.length} из ${state.queue.filter(q=>QueueJournal.section(q)===tab).length}`;
    $('journal-date-error').hidden=!(filters.from&&filters.to&&filters.from>filters.to);
    const key=JSON.stringify([items,action,busy,[...state.sendableQueueIds]]);
    if(key!==rowsKey){
      const list=$('queue-list'),openDetails=new Set([...list.querySelectorAll('details[open]')].map(d=>d.closest('[data-journal-id]')?.dataset.journalId));
      const focused=document.activeElement,focusedId=focused?.closest('[data-journal-id]')?.dataset.journalId,wasCheckbox=focused?.matches('input[type=checkbox]');
      rowsKey=key;list.replaceChildren();let previousDay=null;
      for(const item of items){
        const day=QueueJournal.dayKey(item);
        if(day!==previousDay){previousDay=day;const heading=document.createElement('h3');heading.className='journal-date';heading.textContent=day?new Date(`${day}T12:00:00`).toLocaleDateString('ru-RU',{day:'numeric',month:'long',year:'numeric'}):'Дата не указана';list.append(heading);}
        const element=row(item);if(openDetails.has(item.id))element.querySelector('details')?.setAttribute('open','');list.append(element);
      }
      if(!items.length)list.append(createEmptyState(filterCount?'По этим фильтрам ничего не найдено. Сбросьте или измените фильтр.':tab==='archive'?'Архив пуст. Здесь появятся записи, которые вы уберёте из журнала.':tab==='done'?'Завершённых поручений пока нет.':'Текущих поручений нет. Завершённые — во вкладке «Готовые».'));
      if(focusedId&&wasCheckbox)list.querySelector(`[data-journal-id="${CSS.escape(focusedId)}"] input`)?.focus({preventScroll:true});
    }
    syncSelection();
  }
  function changeTab(next){
    tab=next;archiveMode=false;selected.clear();rowsKey='';render();
    $('journal-message').textContent=tab==='archive'?'Архив сохраняет результаты и исходные даты. Записи можно вернуть без запуска.':'';
  }
  function toggleFilters(){
    const panel=$('journal-filters'),b=$('journal-filter-toggle'),opening=b.getAttribute('aria-expanded')!=='true';
    b.setAttribute('aria-expanded',String(opening));
    if(opening){panel.hidden=false;BoardMotion?.animate(panel,[{opacity:0,transform:'translateY(-5px)'},{opacity:1,transform:'none'}],{duration:180});}
    else {const a=BoardMotion?.animate(panel,[{opacity:1,transform:'none'},{opacity:0,transform:'translateY(-4px)'}],{duration:130});if(a)a.finished.catch(()=>{}).finally(()=>{if(b.getAttribute('aria-expanded')==='false')panel.hidden=true;});else panel.hidden=true;}
  }
  async function file(ids,archived){
    if(busy||!ids.length)return;
    busy=true;++stateLoadGeneration;rowsKey='';render();$('journal-message').textContent='Сохраняем изменения в журнале…';
    try{
      const result=await request('/api/queue/archive',{method:'POST',body:JSON.stringify({queueIds:ids,archived})});
      ++stateLoadGeneration;
      for(const update of result.updated){const item=state.queue.find(q=>q.id===update.id);if(item){if(update.archivedAt)item.archivedAt=update.archivedAt;else delete item.archivedAt;}}
      selected.clear();$('journal-message').textContent=result.message;BoardUI.toast(result.message);
      window.ProjectDetail?.refresh();
    }catch(error){$('journal-message').textContent=`Не удалось подтвердить сохранение: ${error.message} Обновим данные журнала.`;BoardUI.toast(error.message,true);}
    finally{busy=false;rowsKey='';render();await loadState({quiet:true});}
  }
  document.addEventListener('DOMContentLoaded',()=>{
    if(!$('journal-tabs'))return;
    document.querySelectorAll('[data-journal-tab]').forEach(b=>{
      b.addEventListener('click',()=>changeTab(b.dataset.journalTab));
      b.addEventListener('keydown',e=>{const tabs=[...document.querySelectorAll('[data-journal-tab]')],i=tabs.indexOf(b);let next;if(e.key==='ArrowRight')next=(i+1)%tabs.length;else if(e.key==='ArrowLeft')next=(i+tabs.length-1)%tabs.length;else if(e.key==='Home')next=0;else if(e.key==='End')next=tabs.length-1;else return;e.preventDefault();tabs[next].focus();tabs[next].click();});
    });
    $('journal-mode').addEventListener('click',()=>{archiveMode=!archiveMode;selected.clear();rowsKey='';render();});
    $('journal-filter-toggle').addEventListener('click',toggleFilters);
    for(const key of Object.keys(filters))$('journal-'+key).addEventListener('change',e=>{filters[key]=e.target.value;selected.clear();rowsKey='';render();});
    $('journal-filter-reset').addEventListener('click',()=>{for(const key of Object.keys(filters)){filters[key]='';$('journal-'+key).value='';}selected.clear();rowsKey='';render();});
    $('journal-select-all').addEventListener('change',e=>{for(const id of eligible(visible())){if(mode()==='send')sendChoices.set(id,e.target.checked);else if(e.target.checked)selected.add(id);else selected.delete(id);}rowsKey='';render();});
    $('journal-archive-selected').prepend(icon());
    $('journal-archive-selected').addEventListener('click',()=>file(selectedIds(),mode()!=='restore'));
    render();
  });
  return{render,get busy(){return busy;},sendIds:()=>mode()==='send'?selectedIds():[]};
})();
