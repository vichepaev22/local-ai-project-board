/* Deterministic guidance from saved project data; no model calls or auto-dispatch. */
const Attention = (() => {
  const clean = text => String(text || "").replace(/^(?:Вы\s*\+\s*Codex|Codex|Вы)\s*:\s*/i, "");
  const time = value => Date.parse(value) || 0;
  function resolve(project, column, meta = {}, queue = [], context = {}) {
    const items = queue.filter(q => q.projectId === project.id);
    const active = items.filter(q => ["dispatching", "running", "waiting-user", "waiting-busy"].includes(q.status));
    const next = clean(project.nextSteps?.[0]) || "Уточните один проверяемый результат следующего шага.";
    const decision = clean(project.nextSteps?.find(s => /Вы\s*(?:\+\s*Codex)?\s*:/i.test(s))) || next;
    const result = (title, action, tone = "decision", target = "task", source = "Колонка и сохранённый план") => ({title, action, tone, target, source,
      prompt: `Следующий шаг проекта «${project.name}»: ${action}\nОпирайся на текущую цель и результаты. Если нужно моё решение, задай конкретный вопрос. Не выполняй публикации, развёртывание или платные действия без отдельного разрешения.`});
    if (context.loaded === false) return result("Сверяем состояние", "План виден, но очередь ещё не получена. Обновите данные перед запуском.", "check", "refresh", "Ожидаем данные очереди");
    if (context.stale) return result("Нужен свежий сигнал", "Данные доски давно не обновлялись. Обновите состояние, прежде чем повторять поручение.", "check", "refresh", "Последний снимок доски");
    const waiting = active.find(q => q.status === "waiting-user");
    if (waiting) return result("Нужно ваше решение", waiting.attentionMessage || waiting.blockedReason || "Откройте связанную задачу Codex и ответьте на запрос. Новое поручение не заменяет ответ на запрос доступа.", "decision", "results", "Статус текущего поручения");
    if (active.some(q => q.isStale)) return result("Проверьте связь", "Более двух минут нет событий. Посмотрите последний сигнал в задаче Codex; не запускайте копию поручения.", "check", "results", "Последний сигнал исполнителя");
    if (active.some(q => q.status === "waiting-busy")) return result("Дайте задаче закончить", "Связанный диалог занят. Проверьте текущую работу перед повторной отправкой.", "observe", "results", "Статус текущего поручения");
    if (active.length) return result("Можно переключиться", "Codex выполняет поручение. Ваше внимание понадобится для проверки результата или ответа на вопрос.", "observe", "results", "Статус текущего поручения");
    if (items.some(q => q.status === "queued")) {
      const budget = context.budget;
      if (budget?.limitEnforced === false) {
        return budget.dispatchAllowed
          ? result("Проверьте и дайте старт", "Поручение сохранено. Проверьте рабочую папку и текст, затем подтвердите запуск. Доска не измеряет лимиты провайдера Hermes.", "decision", "launch", "Сохранённая очередь")
          : result("Скопируйте поручение", "Ручной режим или исполнитель недоступен. В результатах карточки скопируйте поручение в вашу AI-оболочку.", "check", "results", "Настроенный режим запуска");
      }
      if (!budget?.isLive) return result("Сначала проверьте лимит", "Поручение сохранено. Получите свежий лимит в очереди перед подтверждением отправки.", "check", "launch", "Очередь и доступность лимита");
      if (Math.min(budget.fiveHour.remainingPercent, budget.weekly.remainingPercent) <= 0) return result("Дождитесь сброса лимита", "Поручение уже сохранено. Проверьте время сброса в очереди; повторно добавлять его не нужно.", "observe", "launch", "Текущий лимит Codex");
      return result("Проверьте и дайте старт", "Поручение заряжено. Проверьте текст и лимит, затем подтвердите отправку через «Поехали».", "decision", "launch", "Сохранённая очередь");
    }
    const latest = [...items].sort((a,b) => time(b.lastEventAt || b.completedAt || b.createdAt) - time(a.lastEventAt || a.completedAt || a.createdAt))[0];
    const recent = latest && (context.now || Date.now()) - time(latest.lastEventAt || latest.completedAt || latest.createdAt) < 48*3600*1000;
    if (recent && ["failed", "interrupted", "blocked-external-access"].includes(latest.status)) return result("Разберите последний запуск", latest.blockedReason || latest.error || "Посмотрите причину остановки и определите, что нужно для продолжения.", "check", "results", "Последнее поручение (до 48 часов)");
    const guidance = {
      backlog: ["Выберите первый результат", decision],
      sprint: ["Снимите ближайшую развилку", decision],
      ready: ["Проверьте условие готовности", `Согласуйте результат, затем зарядите поручение: ${next}`],
      doing: ["Проверьте фактический запуск", `Карточка в работе, но активного поручения в очереди нет. Проверьте связанную задачу. Плановый шаг: ${next}`],
      review: ["Примите результат", `Сопоставьте результат с целью проекта и решите: принять или вернуть на доработку. Ближайшая проверка: ${next}`],
      done: ["Закрепите результат", "Проверьте, что цель действительно достигнута, сохраните итог и выберите дату следующего обзора. Колонка «Завершено» сама по себе не подтверждает готовность."],
    };
    const [title, action] = guidance[column] || guidance.backlog;
    const overdue = meta.due && new Date(`${meta.due}T23:59:59`).getTime() < (context.now || Date.now()) && column !== "done";
    return result(overdue ? "Пересогласуйте срок" : title, overdue ? `Указанный срок прошёл. Решите: сократить объём или изменить дату. ${action}` : action);
  }
  return {resolve};
})();
if (typeof module !== "undefined") module.exports = Attention;
