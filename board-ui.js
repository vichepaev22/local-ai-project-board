/* Planning UI; execution continues to use the existing, budget-checked queue. */
window.BoardUI = (() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  let filter = "all", executionFilter = "all", query = "", saving = false, fingerprint = "", toastTimer, renaming;
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  function toast(message, error = false) {
    const box = $("toast"); box.textContent = message; box.classList.toggle("is-error", error); box.hidden = false;
    const dialog = [...document.querySelectorAll("dialog[open]")].at(-1);
    (dialog || document.body).append(box);
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { box.hidden = true; }, error ? 9000 : 4500);
  }
  function open(id) { const d = $(id); if (!d.open) d.showModal(); }
  function close(d) {
    if (!d.open || d.classList.contains("is-closing")) return;
    const finish = () => { d.close(); d.classList.remove("is-closing"); if (d.id === "project-dialog") ProjectDetail.onClose(); };
    if(d.id==='project-dialog'&&window.BoardMotion){d.classList.add('is-closing');return BoardMotion.exit(d,finish);}
    if (reduced()||!window.BoardMotion?.enabled()) return finish(); d.classList.add("is-closing"); setTimeout(finish, 180);
  }
  function columns(select, selected) {
    select.replaceChildren(...state.board.columns.map(c => { const o = el("option", "", c.name); o.value = c.id; return o; }));
    if (selected) select.value = selected;
  }
  function locationOf(id) { return state.board?.columns.find(c => c.cards.includes(id)); }
  function meta(id) { return state.board?.cards[id] || {}; }
  function name(project) { return meta(project.id).title || project.name; }
  function status(id) {
    return ExecutionView.describe(id);
  }
  function lamp(tone) { const n = el("i", `lamp is-${tone}`); n.setAttribute("aria-hidden", "true"); return n; }
  function mono(id) { const p=state.projects.find(p=>p.id===id); return (p ? name(p).trim().split(/\s+/).slice(0,2).map(part=>Array.from(part)[0]).join('') : 'ПР').toUpperCase(); }
  function card(project) {
    const m = meta(project.id), s = status(project.id);
    const node = el("article", `project-card is-${s.tone}`); node.dataset.projectId = project.id; node.dataset.color = m.color || "paper"; node.dataset.execution=s.kind;
    const top = el("div", "card-top"), tags = el("div", "card-tags");
    if (m.important) tags.append(el("span", "tag tag-important", "Важно"));
    if (m.urgent) tags.append(el("span", "tag tag-urgent", "Срочно"));
    const checkbox = el("input", "card-checkbox"); checkbox.type="checkbox"; checkbox.checked=state.selected.has(project.id); checkbox.setAttribute("aria-label", `Выбрать ${name(project)}`);
    checkbox.addEventListener("change", () => { checkbox.checked ? state.selected.add(project.id) : state.selected.delete(project.id); renderSelection(); syncSelection(); });
    top.append(el("span","project-icon",mono(project.id)),tags,checkbox);
    const content = el("button", "card-open"); content.setAttribute("aria-label", `Открыть ${name(project)}`);
    content.append(el("h3", "", name(project)));
    const overview=el('button','card-overview');overview.setAttribute('aria-label',`Цель и стадия: ${name(project)}`);
    overview.append(el("p", "card-copy-text", m.notes || project.goal),el("span","card-stage",`Сейчас: ${project.stage}`),el("span","card-enter","Открыть проект ↗"));
    overview.addEventListener('click',()=>{if(!BoardDrag.ignoreClick)ProjectDetail.open(project.id);});
    if (m.due) { const day = new Date(`${m.due}T23:59:59`); overview.append(el("span",`card-date${day < new Date() ? " is-overdue" : ""}`,`До ${day.toLocaleDateString("ru-RU",{day:"numeric",month:"short"})}`)); }
    content.addEventListener("click", () => { if(!BoardDrag.ignoreClick) ProjectDetail.open(project.id); });
    node.addEventListener("pointerdown", e => { if(e.pointerType === "mouse" && !e.target.closest("input,.card-grip,button:not(.card-open)")) BoardDrag.begin(e,node,project.id); });
    const percent=Number.isFinite(s.item?.progress)?Math.max(0,Math.min(100,s.item.progress)):null;
    const bottom = el("div","card-bottom"), label = el("span","card-status",s.tone === "running" && percent!==null ? `Этап процесса · ${percent}%` : s.text);
    if (s.item) label.title = `${s.text}. Последний сигнал: ${formatAt(s.item.lastEventAt || s.item.completedAt || s.item.createdAt)}`;
    const grip = el("button","card-grip","⠿"); grip.setAttribute("aria-label",`Переместить ${name(project)}`); grip.title="Перетащить; Enter — выбрать колонку";
    grip.addEventListener("click", e => { if (e.detail === 0) { ProjectDetail.open(project.id); $("detail-column").focus(); } });
    grip.addEventListener("pointerdown", e => BoardDrag.begin(e,node,project.id));
    const links=el("div","card-links"), history=el("button","",`История · ${ProjectHistory.entries(project.id,state.board,state.queue).length}`), task=el("button","","＋ Поручение");
    history.setAttribute("aria-label",`История: ${name(project)}`); task.setAttribute("aria-label",`Новое поручение: ${name(project)}`);
    history.addEventListener("click",()=>ProjectDetail.open(project.id,false,"history")); task.addEventListener("click",()=>ProjectDetail.open(project.id,false,"task")); links.append(history,task);
    bottom.append(lamp(s.tone),label,grip); node.append(ExecutionView.contour(),top,content,ExecutionView.card(project,s),overview,AttentionView.card(project),links,bottom);
    if (s.tone === "running" && percent!==null) { const p = el("div","card-progress"), bar = el("span"); p.title="Этап процесса, не процент готовности результата"; bar.style.width=`${percent}%`; p.append(bar); node.append(p); }
    return node;
  }
  function syncSelection() { $("selected-count").textContent=state.selected.size ? `(${state.selected.size})` : ""; }
  function render() {
    if (!state.board || BoardDrag.active) return;
    ExecutionView.summary(executionFilter);
    const executionKinds=state.projects.map(p=>status(p.id).entries.map(e=>e.kind));
    const key = JSON.stringify([state.board,state.projects,state.queue,state.budget,!!state.lastLoadedAt,Date.now()-state.lastLoadedAt>90000,state.executionLoadError,executionKinds,executionFilter,filter,query,[...state.selected]]);
    if (key === fingerprint) return; fingerprint=key;
    document.body.dataset.theme=state.board.theme;
    $("board-title").textContent=state.board.name; $("sprint-caption").textContent=state.board.sprint; $("project-count").textContent=state.projects.length;
    document.title=`${state.board.name} · Доска`;
    const board = $("project-list"), left = board.scrollLeft, top = board.scrollTop, positions=window.BoardMotion?.positions();
    const focusId = document.activeElement?.closest("[data-project-id]")?.dataset.projectId;
    const focusKind = document.activeElement?.className;
    board.replaceChildren();
    const map = new Map(state.projects.map(p => [p.id,p]));
    for (const col of state.board.columns) {
      const section=el("section","board-column"); section.dataset.column=col.id; section.setAttribute("aria-label", col.name);
      const head=el("header","column-heading"); const visible=col.cards.map(id=>map.get(id)).filter(p=>p && matches(p));
      const title=el("h2","",col.name), edit=el("button","icon-button","···"); edit.setAttribute("aria-label",`Переименовать колонку ${col.name}`);
      edit.addEventListener("click",()=>{renaming=col.id; $("column-name").value=col.name; open("column-dialog");});
      head.append(el("span","column-dot"),title,el("span","column-number",String(visible.length)),edit);
      const list=el("div","column-cards"); for(const p of visible) list.append(card(p));
      if(!visible.length) list.append(el("p","column-empty",filter!=="all"||executionFilter!=="all"||query ? "Нет подходящих карточек" : "Перетащите карточку сюда"));
      const add=el("button","column-add","＋ Добавить карточку"); add.addEventListener("click",()=>addProject(col.id));
      section.append(head,list,add); board.append(section);
    }
    board.scrollLeft=left; board.scrollTop=top;
    if(positions)BoardMotion.flip(positions);
    if (focusId && typeof focusKind === "string") board.querySelector(`[data-project-id="${CSS.escape(focusId)}"] .${CSS.escape(focusKind)}`)?.focus({preventScroll:true});
    const queued=state.queue.filter(q=>q.status==="queued"); const charged=new Set(queued.map(q=>q.projectId)).size;
    $("charged-count").textContent=charged; $("launch-label").textContent=charged ? `Поехали · ${charged}` : "Поехали";
    $("launch-button").disabled=!queued.length;
    $("charge-summary").textContent=charged ? `Поручений к отправке: ${queued.length}` : "Добавьте поручение внутри карточки";
    syncSelection(); ProjectDetail.refresh();if(state.lastLoadedAt)window.BoardMotion?.observe(state.queue);
  }
  function matches(p) { const m=meta(p.id); return (executionFilter==='all'||status(p.id).categories.includes(executionFilter)) && (!query || `${name(p)} ${p.goal} ${m.notes||""}`.toLowerCase().includes(query)) && (filter==="all" || (filter==="charged" ? status(p.id).charged>0 : m[filter])); }
  function filterExecution(kind) {
    executionFilter=executionFilter===kind?'all':kind;filter='all';query='';$('project-search').value='';
    document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('is-active',b.dataset.filter==='all');b.setAttribute('aria-pressed',String(b.dataset.filter==='all'));});
    render();const board=$('project-list');board.scrollLeft=0;board.scrollTop=0;
    const first=board.querySelector('.project-card');if(first)first.scrollIntoView({block:'nearest',inline:'center',behavior:BoardMotion.enabled()?'smooth':'instant'});
  }
  async function save(operation) {
    if (saving) { toast("Сохраняем предыдущее изменение. Повторите через секунду."); return false; }
    saving=true; $("save-status").textContent="Сохраняем…";
    try {
      const response=await fetch("/api/board",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:state.board.revision,...operation}),signal:AbortSignal.timeout(10000)});
      const data=await response.json();
      if(data.board) state.board=data.board;
      if(data.projects) state.projects=data.projects;
      if(!response.ok) throw new Error(data.error||"Не удалось сохранить доску.");
      $("save-status").textContent="Сохранено на этом компьютере"; render(); return true;
    } catch(error) { $("save-status").textContent="Изменение не подтверждено"; toast(error.message||"Ошибка сохранения",true); render(); return false; }
    finally { saving=false; }
  }
  async function move(projectId,columnId,beforeId=null) { const previous=locationOf(projectId)?.id;const ok=await save({op:"move",projectId,columnId,beforeId}); if(ok){toast(`Карточка перемещена: ${locationOf(projectId).name}`);BoardMotion?.glow(BoardMotion.card(projectId),previous!=='done'&&columnId==='done'&&status(projectId).tone==='done'?'accepted':'land');} return ok; }
  function addProject(column="backlog") { columns($("new-project-column"),column); open("add-dialog"); }
  function settings() { if(!state.board)return; $("board-name").value=state.board.name; $("board-sprint").value=state.board.sprint; $("board-theme").value=state.board.theme; $("board-discussion").value=state.board.discussionUrl; open("settings-dialog"); }
  function link(anchor,url) { anchor.hidden=!url; if(url)anchor.href=url; else anchor.removeAttribute("href"); }
  function brief(p) { return `${name(p)}\nКолонка: ${locationOf(p.id)?.name||""}\nЦель: ${p.goal}\nСейчас: ${p.stage}\nШаги:\n${p.nextSteps.map((s,i)=>`${i+1}. ${s}`).join("\n")}\n${meta(p.id).notes ? `Заметка: ${meta(p.id).notes}\n` : ""}`; }
  async function copy(text) { try { await navigator.clipboard.writeText(text); toast("Скопировано. Вставьте текст в выбранную AI-оболочку или обсуждение."); } catch { toast("Браузер не разрешил копирование. Разрешите доступ к буферу обмена.",true); } }
  document.addEventListener("DOMContentLoaded",()=>{
    document.querySelectorAll("[data-open]").forEach(b=>b.addEventListener("click",()=>open(b.dataset.open)));
    document.querySelectorAll("[data-board-home]").forEach(b=>b.addEventListener("click",()=>{filter="all";query="";$("project-search").value="";document.querySelector('[data-filter="all"]').click();$("project-list").scrollLeft=0;$("project-list").scrollTop=0;}));
    document.querySelectorAll("[data-close]").forEach(b=>b.addEventListener("click",()=>close(b.closest("dialog"))));
    document.querySelectorAll("dialog").forEach(d=>{d.addEventListener("cancel",e=>{e.preventDefault();close(d);});d.addEventListener("click",e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close(d);}});});
    $("launch-button").addEventListener("click",()=>open("launch-dialog"));
    $("settings-button").addEventListener("click",settings); $("bulk-button").addEventListener("click",()=>open("bulk-dialog"));
    $("add-project-button").addEventListener("click",()=>addProject());
    $("project-search").addEventListener("input",e=>{query=e.target.value.toLowerCase().trim();render();});
    document.querySelectorAll("[data-filter]").forEach(b=>b.addEventListener("click",()=>{executionFilter='all';filter=b.dataset.filter;document.querySelectorAll("[data-filter]").forEach(n=>{n.classList.toggle("is-active",n===b);n.setAttribute("aria-pressed",String(n===b));});render();}));
    $("sharing-button").addEventListener("click",()=>{link($("board-discussion-link"),state.board?.discussionUrl);open("sharing-dialog");});
    $("link-discussion").addEventListener("click",()=>{$("sharing-dialog").close();settings();$("board-discussion").focus();});
    $("copy-board").addEventListener("click",()=>copy(`${state.board.name}\n${state.board.sprint}\n\n${state.board.columns.flatMap(c=>c.cards).map(id=>brief(state.projects.find(p=>p.id===id))).join("\n")}\nЭто снимок доски для обсуждения; перемещения здесь не синхронизируются с локальным сайтом.`));
    $("board-settings-form").addEventListener("submit",async e=>{e.preventDefault();if(await save({op:"settings",name:$("board-name").value,sprint:$("board-sprint").value,theme:$("board-theme").value,discussionUrl:$("board-discussion").value}))close($("settings-dialog"));});
    $("column-form").addEventListener("submit",async e=>{e.preventDefault();if(await save({op:"rename-column",columnId:renaming,name:$("column-name").value}))close($("column-dialog"));});
    $("add-project-form").addEventListener("submit",async e=>{e.preventDefault();if(await save({op:"add-project",name:$("new-project-name").value,goal:$("new-project-goal").value,workspace:$("new-project-workspace").value,columnId:$("new-project-column").value})){e.target.reset();close($("add-dialog"));toast("Новая карточка добавлена. Поручения ещё не запускались.");}});
  });
  function reveal(id){filter='all';query='';$('project-search').value='';document.querySelector('[data-filter="all"]').click();BoardMotion.spotlight(id);}
  return {$,el,open,close,toast,columns,locationOf,meta,name,status,lamp,mono,render,save,move,link,brief,copy,reveal,filterExecution,get saving(){return saving;}};
})();
