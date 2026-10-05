/* Intentionally self-contained: no fetch, sockets, storage, or real portfolio imports. */
const Demo = (()=>{
  const $=id=>document.getElementById(id), make=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls||'';if(text)n.textContent=text;return n;};
  const projects=[{id:'demo-alpha',name:'Новый продукт',goal:'Проверить один клиентский сценарий',color:'sand'},{id:'demo-beta',name:'История бренда',goal:'Собрать понятную презентацию',color:'sage'},{id:'demo-gamma',name:'Первый пилот',goal:'Получить обратную связь команды',color:'blue'}];
  let stage=0,timers=[],events=[],active=null;
  const schedule=(fn,ms)=>{const timer=setTimeout(fn,ms);timers.push(timer);return timer;};
  function record(text){events.unshift(text);$('demo-history').replaceChildren(...events.map(text=>{const li=make('li','history-event');li.append(make('span','history-meta','Событие демо'),make('h4','',text));return li;}));BoardMotion.historyReveal($('demo-history'));}
  function setStatus(id,tone,text){const n=BoardMotion.card(id);n.classList.remove('is-charged','is-running','is-done');if(tone!=='idle')n.classList.add(`is-${tone}`);n.querySelector('.demo-status').replaceChildren(make('i',`lamp is-${tone}`),make('span','',text));}
  function close(){const d=$('demo-dialog');if(!d.open)return;BoardMotion.exit(d,()=>d.close());}
  function open(id){active=id;const p=projects.find(p=>p.id===id);$('demo-title').textContent=p.name;$('demo-dialog').showModal();$('demo-dialog').scrollTop=0;BoardMotion.enter($('demo-dialog'),id);}
  function move(id,column,before=null){const n=BoardMotion.card(id),list=document.querySelector(`[data-column="${column}"] .column-cards`),positions=BoardMotion.positions();list.insertBefore(n,before?BoardMotion.card(before):null);BoardMotion.flip(positions);BoardMotion.glow(n,'land');record(`«${projects.find(p=>p.id===id).name}» → ${list.closest('.board-column').querySelector('h2').textContent}`);return true;}
  function charge(){for(const p of projects.slice(0,2))setStatus(p.id,'charged','Демо: готово к отправке');record('Два вымышленных поручения заряжены');}
  function launch(){close();schedule(()=>{BoardMotion.launch(projects.slice(0,2).map(p=>p.id));for(const p of projects.slice(0,2))setStatus(p.id,'running','Симуляция выполнения · не Codex');record('Началась симуляция выполнения');},200);}
  const captions=['Покажите весь сценарий за 35 секунд или исследуйте доску сами.','Погружение: карточка становится рабочим пространством.','Перемещение: соседние карточки освобождают место.','Зарядка: свет показывает подготовленные поручения.','Поехали: импульс запускает мягкое ламповое дыхание.','Получен демо-результат. Это ещё не приёмка.','Результат принят в демо. Все события остались в истории.'];
  function next(){
    if(stage>=6){halt();return;}stage++;$('demo-count').textContent=`ШАГ ${stage} / 6`;$('demo-caption').textContent=captions[stage];
    if(stage===1)open('demo-alpha');
    if(stage===2){close();schedule(()=>move('demo-alpha','demo-doing'),200);}
    if(stage===3)charge();
    if(stage===4)launch();
    if(stage===5){for(const p of projects.slice(0,2)){setStatus(p.id,'done','Демо-результат готов');BoardMotion.glow(BoardMotion.card(p.id));}record('Получены два демо-результата');}
    if(stage===6){move('demo-alpha','demo-done');BoardMotion.glow(BoardMotion.card('demo-alpha'),'accepted');record('Демо-результат принят');halt();}
  }
  function halt(){timers.forEach(clearTimeout);timers=[];$('demo-play').disabled=false;$('demo-stop').disabled=true;}
  function reset(){halt();if($('demo-dialog').open)$('demo-dialog').close();stage=0;events=[];active=null;$('demo-history').replaceChildren();$('demo-count').textContent='ШАГ 0 / 6';$('demo-caption').textContent=captions[0];$('demo-board').replaceChildren();
    for(const [id,title] of [['demo-ideas','Идеи'],['demo-doing','В работе'],['demo-done','Принято']]){const col=make('section','board-column');col.dataset.column=id;const head=make('header','column-heading');head.append(make('span','column-dot'),make('h2','',title));col.append(head,make('div','column-cards'));$('demo-board').append(col);}
    for(const p of projects){const n=make('article','project-card');n.dataset.projectId=p.id;n.dataset.color=p.color;const body=make('div','demo-card-body'),button=make('button','card-open');button.setAttribute('aria-label',`Открыть демо: ${p.name}`);button.append(make('h3','',p.name),make('p','',p.goal));button.addEventListener('click',()=>{if(!BoardDrag.ignoreClick){halt();open(p.id);}});body.append(button);const status=make('div','demo-status');status.append(make('i','lamp'),make('span','','Демо: планирование'));const grip=make('button','card-grip','⠿');grip.setAttribute('aria-label',`Переместить демо: ${p.name}`);grip.addEventListener('pointerdown',e=>{halt();BoardDrag.begin(e,n,p.id);});grip.addEventListener('click',e=>{if(e.detail===0){halt();const col=n.closest('.board-column').dataset.column;move(p.id,col==='demo-ideas'?'demo-doing':col==='demo-doing'?'demo-done':'demo-ideas');}});status.append(grip);n.append(body,status);n.addEventListener('pointerdown',e=>{if(e.pointerType==='mouse'&&e.target.closest('.card-open')){halt();BoardDrag.begin(e,n,p.id);}});document.querySelector('[data-column="demo-ideas"] .column-cards').append(n);}
  }
  $('demo-play').addEventListener('click',()=>{reset();$('demo-play').disabled=true;$('demo-stop').disabled=false;next();timers=[6000,12000,18000,27000,35000].map(ms=>setTimeout(next,ms));});
  $('demo-next').addEventListener('click',()=>{halt();next();});$('demo-stop').addEventListener('click',halt);$('demo-reset').addEventListener('click',reset);$('launch-button').addEventListener('click',()=>{halt();launch();});$('demo-close').addEventListener('click',()=>{halt();close();});$('demo-charge').addEventListener('click',()=>{halt();setStatus(active,'charged','Поручение сохранено только в демо');record('Демо-поручение добавлено');close();});
  $('demo-dialog').addEventListener('cancel',e=>{e.preventDefault();halt();close();});document.addEventListener('visibilitychange',()=>{if(document.hidden)halt();});
  reset();return{move};
})();
window.BoardUI={saving:false,move:async(id,column,before)=>Demo.move(id,column,before)};
