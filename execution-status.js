/* Read-only interpretation of queue evidence. Planning columns are not execution. */
const ExecutionStatus = (() => {
  const active = new Set(['running', 'dispatching', 'waiting-user', 'waiting-busy']);
  const labels = {running:'Выполняется', dispatching:'Отправляется', waiting:'Ожидает', stale:'Статус требует проверки', error:'Ошибка', queued:'Готово к отправке', done:'Поручение завершено', idle:'Нет активных поручений', unknown:'Сверяем состояние'};
  const time = value => Date.parse(value) || 0;
  const eventTime = q => time(q.lastEventAt || q.completedAt || q.startedAt || q.createdAt);
  function fresh(context) {
    return Boolean(context.lastLoadedAt && !context.loadError && context.now - context.lastLoadedAt <= 90000);
  }
  function errorText(q) {
    let message = String(q.error || '');
    try { const data = JSON.parse(message); message = String(data.detail || data.message || message); } catch {}
    if (/requires a newer version of Codex/i.test(message)) return 'Для выбранной модели нужна более новая версия Codex. Обновите Codex перед повтором.';
    if (/failed to deserialize|unknown variant/i.test(message)) return 'Codex не смог прочитать формат сохранённой переписки. Проверьте версию и подробности ошибки.';
    if (q.status === 'interrupted') return 'Запуск остановлен. Проверьте сохранённый результат перед повтором.';
    return message.replace(/\s+/g, ' ').trim().slice(0, 220) || 'Запуск завершился ошибкой. Подробности — в результатах.';
  }
  function item(q, context) {
    let kind = 'unknown', label, detail = q.progressStage || '';
    if (q.status === 'waiting-user') { kind='waiting'; label='Нужен ваш ответ'; detail='Откройте связанный диалог Codex и ответьте на запрос.'; }
    else if (q.status === 'waiting-busy') { kind='waiting'; label='Диалог занят'; detail='Поручение ожидает освобождения диалога; это не выполнение.'; }
    else if (q.status === 'blocked-external-access') { kind='waiting'; label='Нужны доступы'; detail='Проверьте запрос доступа в результатах проекта.'; }
    else if (['running','dispatching'].includes(q.status)) {
      const signal = time(q.lastEventAt || q.startedAt);
      if (!fresh(context) || q.isStale || !signal || context.now-signal>120000) {
        kind='stale'; detail=!fresh(context)?'Не удалось подтвердить свежесть данных. Последний статус сохранён.':'Давно нет сигнала. Это не подтверждение зависания — проверьте диалог.';
      } else kind=q.status;
    } else if (q.status==='queued') kind='queued';
    else if (q.status==='completed') kind='done';
    else if (['failed','interrupted'].includes(q.status)) { kind='error'; detail=errorText(q); label=q.status==='interrupted'?'Запуск остановлен':q.progressStage==='Не удалось отправить'?'Ошибка запуска':'Ошибка'; }
    return {kind, label:label || labels[kind], detail, item:q};
  }
  function project(id, queue, context) {
    if (!context.lastLoadedAt) return {kind:'unknown',label:labels.unknown,text:labels.unknown,tone:'idle',entries:[],categories:[],charged:0};
    const items=queue.filter(q=>q.projectId===id).slice().sort((a,b)=>eventTime(b)-eventTime(a));
    const pending=items.filter(q=>active.has(q.status)||q.status==='queued');
    const entries=(pending.length?pending:items.slice(0,1)).map(q=>item(q,context));
    const order=['stale','waiting','running','dispatching','queued','error','done','unknown'];
    const primary=entries.slice().sort((a,b)=>order.indexOf(a.kind)-order.indexOf(b.kind))[0] || {kind:'idle',label:labels.idle};
    const tone={running:'running',dispatching:'dispatching',queued:'charged',done:'done',error:'error',stale:'attention',waiting:'attention'}[primary.kind] || 'idle';
    return {...primary, text:primary.label, tone, entries, categories:[...new Set(entries.map(e=>e.kind))], charged:items.filter(q=>q.status==='queued').length};
  }
  function summary(projects, queue, context) {
    const groups=Object.fromEntries(['running','dispatching','waiting','stale','error','queued','done'].map(k=>[k,[]]));
    for(const p of projects) for(const kind of project(p.id,queue,context).categories) groups[kind]?.push(p.id);
    return groups;
  }
  function relative(value, now) {
    if (!time(value)) return 'время сигнала неизвестно';
    const seconds=Math.max(0,Math.floor((now-time(value))/1000));
    if(seconds<60)return `сигнал ${seconds} с назад`;
    if(seconds<3600)return `сигнал ${Math.floor(seconds/60)} мин назад`;
    if(seconds<86400)return `сигнал ${Math.floor(seconds/3600)} ч назад`;
    return `сигнал ${Math.floor(seconds/86400)} дн назад`;
  }
  return {project,summary,item,fresh,relative,errorText};
})();
if(typeof module!=='undefined')module.exports=ExecutionStatus;
