/* Pure presentation policy. The server independently enforces execution rules. */
const HarnessMode = (() => {
  function policy(dispatch = {}, budget = {}) {
    const kind = dispatch.kind || 'manual';
    if (kind === 'hermes') return {kind, name:'Hermes', allowed: Boolean(dispatch.online && budget.dispatchAllowed), capacity:Infinity};
    if (kind !== 'codex') return {kind:'manual', name:'Ручной режим', allowed:false, capacity:0};
    const percentages = [budget.fiveHour?.remainingPercent, budget.weekly?.remainingPercent];
    const capacity = percentages.every(Number.isFinite) ? Math.max(0, Math.min(...percentages)) : 0;
    return {kind, name:'Codex', allowed:Boolean(budget.isLive && capacity > 0), capacity};
  }
  function prompt(project, items) {
    const labels = {'next-step':'ближайший шаг',goal:'цель проекта',comment:'комментарий'};
    return `Задача из доски проектов для проекта «${project.name}».\n` +
      `Обработай связанные запросы согласованно, в финале дай отдельный проверяемый статус по каждому пункту.\n` +
      items.map((item,i)=>`${i+1}. ${labels[item.kind] || 'изменение'}: ${item.text}`).join('\n') +
      '\n\nРаботай только в рамках запроса. Не публикуй материалы, не отправляй внешние сообщения и не меняй внешние настройки без отдельного подтверждения.';
  }
  return {policy,prompt};
})();
if (typeof module !== 'undefined') module.exports = HarnessMode;
