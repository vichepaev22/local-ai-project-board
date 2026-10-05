/* Only saved, project-scoped events. No guessed historical edits. */
const ProjectHistory = (() => {
  const labels = {queued:"Поручение добавлено", dispatching:"Отправка в Codex", running:"Выполнение началось", "waiting-user":"Запрошено ваше решение", "waiting-busy":"Связанная задача занята", completed:"Получен результат", failed:"Ошибка запуска", interrupted:"Выполнение остановлено", "blocked-external-access":"Нужны доступы"};
  function entries(projectId, board, queue) {
    const events = (board?.history || []).filter(e => e.projectId === projectId).map(e => ({...e, source:"Доска"}));
    for (const q of queue.filter(q => q.projectId === projectId)) {
      if(q.createdAt) events.push({at:q.createdAt, title:q.kind === "goal" ? "Предложено уточнение цели" : "Добавлено поручение", text:q.text, source:"Очередь", modelLabel:q.model ? q.modelLabel||q.model : ''});
      const isFinal = event => event.status===q.status && Date.parse(event.at)===Date.parse(q.completedAt);
      for (const event of q.history || []) events.push({at:event.at, title:labels[event.status] || event.status, text:isFinal(event)?(q.result || q.error || q.blockedReason || event.text):event.text, source:"Исполнитель"});
      if (q.completedAt && !(q.history || []).some(isFinal)) events.push({at:q.completedAt, title:labels[q.status] || "Итог поручения", text:q.result || q.error || q.blockedReason || q.progressStage, source:"Сохранённый итог"});
    }
    return events.sort((a,b) => (Date.parse(b.at)||0) - (Date.parse(a.at)||0));
  }
  function render(container, events) {
    const {el} = BoardUI;
    if (!events.length) { container.replaceChildren(el("li", "empty-state", "Изменения ещё не записывались. Здесь появятся перемещения, правки карточки и события поручений.")); return; }
    const value = v => typeof v === "boolean" ? (v ? "Да" : "Нет") : String(v ?? "") || "Не задано";
    container.replaceChildren(...events.map(event => {
      const row=el("li","history-event"), date=el("time","",formatAt(event.at)); date.dateTime=event.at;
      const meta=el("div","history-meta"); meta.append(date,el("span","",event.source));
      row.append(meta,el("h4","",event.title));
      if(event.modelLabel)row.append(el('small','queue-model',`Модель: ${event.modelLabel}`));
      if(event.text) { const details=el("details","history-text"); details.append(el("summary","",String(event.text).slice(0,125)+(event.text.length>125?"…":"")),el("p","",event.text)); row.append(details); }
      for(const change of event.changes || []) {
        if(change.field==='Колонка')row.append(el('p','history-route',`${value(change.before)} → ${value(change.after)}`));
        const diff=el("details","history-diff"); diff.append(el("summary","",change.field),el("p","",`Было: ${value(change.before)}`),el("p","",`Стало: ${value(change.after)}`)); row.append(diff);
      }
      return row;
    }));
  }
  return {entries,render};
})();
if (typeof module !== "undefined") module.exports = ProjectHistory;
