const state = { projects: [], board: null, tomorrowPlan: null, budget: null, queue: [], activity: [], dispatch: null, selected: new Set(), sendableQueueIds: new Set(), lastLoadedAt: 0, executionLoadError: false };
let stateLoadGeneration = 0;
const scopePoints = { small: 4, normal: 11, deep: 24 };
const scopeLabels = { small: "малая", normal: "обычная", deep: "глубокая" };
const kindLabels = { "next-step": "Шаг", goal: "Цель", comment: "Комментарий" };
const activeStatuses = new Set(["dispatching", "running", "waiting-user", "waiting-busy"]);
const statusMeta = {
  queued: { label: "В очереди", progress: 0, index: 0, tone: "muted" },
  dispatching: { label: "Отправляется", progress: 10, index: 1, tone: "working" },
  running: { label: "В работе", progress: 55, index: 2, tone: "working" },
  "waiting-user": { label: "Нужно ваше решение", progress: 70, index: 2, tone: "attention" },
  "waiting-busy": { label: "Диалог занят", progress: 15, index: 1, tone: "attention" },
  completed: { label: "Готово", progress: 100, index: 3, tone: "success" },
  failed: { label: "Не отправлено", progress: 0, index: 1, tone: "danger" },
  interrupted: { label: "Остановлено", progress: 100, index: 3, tone: "danger" },
  "blocked-external-access": { label: "Нужны доступы", progress: 60, index: 2, tone: "attention" },
};
const executionSteps = ["В очереди", "Отправлено", "AI работает", "Итог"];

const dom = {
  budgetGrid: document.querySelector("#budget-grid"),
  budgetNote: document.querySelector("#budget-note"),
  tomorrowDate: document.querySelector("#tomorrow-date"),
  tomorrowTitle: document.querySelector("#tomorrow-title"),
  tomorrowNote: document.querySelector("#tomorrow-note"),
  tomorrowList: document.querySelector("#tomorrow-list"),
  projectList: document.querySelector("#project-list"),
  queueList: document.querySelector("#queue-list"),
  planMessage: document.querySelector("#plan-message"),
  activityList: document.querySelector("#activity-list"),
  selectionSummary: document.querySelector("#selection-summary"),
  confirmButton: document.querySelector("#confirm-button"),
  bulkText: document.querySelector("#bulk-text"),
  bulkScope: document.querySelector("#bulk-scope"),
  dispatchStatus: document.querySelector("#dispatch-status"),
};

function formatDate(unixSeconds) {
  if (!Number.isFinite(unixSeconds)) return "время сброса неизвестно";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(unixSeconds * 1000));
}

function formatAt(iso) {
  if (!iso) return "ещё не было";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "неизвестно";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function getMeta(item) {
  const base = statusMeta[item.status] || statusMeta.failed;
  return { ...base, progress: Number.isFinite(item.progress) ? item.progress : base.progress };
}

function getQueuedItems() {
  return state.queue.filter((item) => item.status === "queued" && !item.archivedAt);
}

function getPointTotal(queue) {
  return getDispatchGroups(queue).reduce((total, group) => total + group.points, 0);
}

function getDispatchGroups(queue) {
  const grouped = new Map();
  queue.forEach((item) => {
    const key = item.projectId || item.id;
    const group = grouped.get(key) || { projectName: item.projectName, items: [], points: 0 };
    group.items.push(item);
    group.points = Math.max(group.points, scopePoints[item.scope]);
    grouped.set(key, group);
  });
  return [...grouped.values()];
}

function buildBatches(queue, capacity) {
  const ordered = getDispatchGroups(queue).sort((left, right) => left.points - right.points);
  const batches = [];
  let current = [];
  let currentPoints = 0;
  ordered.forEach((group) => {
    const points = group.points;
    if (current.length && currentPoints + points > capacity) {
      batches.push(current);
      current = [];
      currentPoints = 0;
    }
    current.push(group);
    currentPoints += points;
  });
  if (current.length) batches.push(current);
  return batches;
}

async function request(url, options = {}) {
  const { timeoutMs = 10_000, ...fetchOptions } = options;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { headers: { "Content-Type": "application/json" }, ...fetchOptions, signal: controller.signal });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Не удалось выполнить действие.");
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("Сервер не ответил за 10 секунд. Обновите экран — очередь сохранена.");
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function loadState({ quiet = false } = {}) {
  if (window.QueueJournalUI?.busy) return;
  const generation = ++stateLoadGeneration;
  try {
    const data = await request("/api/state");
    if (generation !== stateLoadGeneration) return;
    state.projects = data.projects;
    if (data.board && (!state.board || data.board.revision >= state.board.revision)) state.board = data.board;
    state.tomorrowPlan = data.tomorrowPlan;
    state.budget = data.budget;
    state.queue = data.queue;
    state.activity = data.activity;
    state.dispatch = data.dispatch;
    state.lastLoadedAt = Date.now();
    state.executionLoadError = false;
    render();
    window.ProjectDetail?.restore();
  } catch (error) {
    if (generation !== stateLoadGeneration) return;
    state.executionLoadError = true;
    window.BoardUI?.render();
    if (!quiet) { showPlan(`Не удалось загрузить дашборд: ${error.message}`, true); window.BoardUI?.toast(error.message, true); }
  }
}

function renderBudget() {
  if (!state.budget) return;
  const mode = HarnessMode.policy(state.dispatch || {}, state.budget);
  document.querySelector('#budget-heading').textContent=mode.kind==='codex' ? 'Осталось в Codex' : 'Исполнитель';
  if (mode.kind !== 'codex') {
    dom.budgetGrid.replaceChildren(createBudgetItem('Режим',mode.name,mode.kind==='manual'?'Без аккаунта и вызовов моделей':mode.allowed?'CLI найден':'CLI недоступен'));
    dom.budgetNote.textContent=mode.kind==='manual'?'Добавляйте проекты и копируйте поручения в любую AI-оболочку. Для автоматического запуска перезапустите с --bridge codex или --bridge hermes.':'Лимиты и стоимость определяет ваш провайдер Hermes. Доска их не измеряет; глубина — только оценка объёма работы.';
    return;
  }
  const { fiveHour, weekly, note, capturedAt, isLive, source, error } = state.budget;
  dom.budgetGrid.replaceChildren(
    createBudgetItem("5 часов", Number.isFinite(fiveHour.remainingPercent)?`${fiveHour.remainingPercent}%`:'Неизвестно', `до сброса: ${formatDate(fiveHour.resetsAt)}`),
    createBudgetItem("Неделя", Number.isFinite(weekly.remainingPercent)?`${weekly.remainingPercent}%`:'Неизвестно', `до сброса: ${formatDate(weekly.resetsAt)}`),
  );
  const freshness = isLive ? "Обновлено" : "Последний доступный снимок";
  dom.budgetNote.textContent = `${note} ${freshness}: ${formatAt(capturedAt)}.${error ? ` ${error}` : ""}`;
}

function createBudgetItem(label, value, detail) {
  const element = document.createElement("div");
  element.className = "budget-item";
  const labelElement = document.createElement("span");
  const valueElement = document.createElement("strong");
  const detailElement = document.createElement("span");
  labelElement.textContent = label;
  valueElement.textContent = value;
  detailElement.textContent = detail;
  element.append(labelElement, valueElement, detailElement);
  return element;
}

function renderDispatchStatus() {
  if (!dom.dispatchStatus || !state.dispatch) return;
  dom.dispatchStatus.textContent = state.dispatch.message;
  dom.dispatchStatus.classList.toggle("is-online", Boolean(state.dispatch.online));
}

function renderTomorrowPlan() {
  const plan = state.tomorrowPlan;
  if (!plan || !dom.tomorrowList) return;
  dom.tomorrowDate.textContent = plan.label || "Завтра";
  dom.tomorrowTitle.textContent = plan.title || "Фокус на завтра";
  dom.tomorrowNote.textContent = plan.note || "";
  dom.tomorrowList.replaceChildren();
  (plan.tasks || []).forEach((task) => {
    const row = document.createElement("li");
    row.className = "tomorrow-task";
    const priority = document.createElement("span");
    priority.className = `tomorrow-priority${task.status === "blocked" ? " is-blocked" : ""}`;
    priority.textContent = task.priority || "План";
    const copy = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = task.project || "Проект";
    const taskText = document.createElement("p");
    taskText.textContent = task.task || "";
    const outcome = document.createElement("p");
    outcome.className = "tomorrow-outcome";
    outcome.textContent = `Готово, когда: ${task.doneWhen || "результат подтверждён"}`;
    copy.append(heading, taskText, outcome);
    const owner = document.createElement("small");
    owner.textContent = `${task.owner || ""}${task.statusLabel ? ` · ${task.statusLabel}` : ""}`;
    row.append(priority, copy, owner);
    dom.tomorrowList.append(row);
  });
}

function renderProjects() {
  if (window.BoardUI) { BoardUI.render(); return; }
  const template = document.querySelector("#project-template");
  dom.projectList.replaceChildren();
  state.projects.forEach((project) => {
    const card = template.content.cloneNode(true);
    const article = card.querySelector("article");
    const checkbox = card.querySelector("input[type=checkbox]");
    const route = card.querySelector(".route-badge");
    article.dataset.projectId = project.id;
    card.querySelector("h3").textContent = project.name;
    card.querySelector(".stage").textContent = project.stage;
    card.querySelector(".goal").textContent = project.goal;
    project.nextSteps.forEach((step) => {
      const item = document.createElement("li");
      item.textContent = step;
      card.querySelector(".next-steps").append(item);
    });
    checkbox.checked = state.selected.has(project.id);
    checkbox.addEventListener("change", () => {
      checkbox.checked ? state.selected.add(project.id) : state.selected.delete(project.id);
      renderSelection();
    });
    route.textContent = project.route.label;
    route.classList.add(project.route.status === "linked" ? "is-linked" : "is-auto-route");
    card.querySelector("form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const textarea = event.currentTarget.querySelector("textarea");
      const kind = event.currentTarget.querySelector(".kind-select").value;
      const scope = event.currentTarget.querySelector(".scope-select").value;
      if (!textarea.value.trim()) return showPlan("Напишите изменение, которое нужно добавить.", true);
      await queueUpdates([{ projectId: project.id, kind, scope, text: textarea.value.trim() }]);
      textarea.value = "";
    });
    dom.projectList.append(card);
  });
  renderSelection();
}

function renderSelection() {
  const count = state.selected.size;
  dom.selectionSummary.textContent = count ? `Выбрано: ${count}` : "Ничего не выбрано";
}

function renderQueue() {
  const queued = getQueuedItems();
  const active = state.queue.filter((item) => activeStatuses.has(item.status));
  const points = getPointTotal(queued);
  const mode = HarnessMode.policy(state.dispatch || {}, state.budget || {});
  const available = mode.capacity;
  const fits = points <= available;
  const batches = queued.length ? buildBatches(queued, Math.max(1, available)) : [];
  const sendable = !mode.allowed ? [] : fits ? queued : getDispatchGroups(queued).filter(group => group.points <= available).reduce((selected, group) => getPointTotal(selected) + group.points <= available ? selected.concat(group.items) : selected, []);
  state.sendableQueueIds = new Set(sendable.map((item) => item.id));
  document.querySelector('#harness-warning').hidden=mode.kind!=='hermes';
  if (!state.queue.length) {
    showPlan("Очередь пуста. Добавьте изменение в одной карточке или сразу в выбранные проекты.");
    dom.queueList.replaceChildren(createEmptyState("Ни одно изменение ещё не ждёт расчёта."));
    dom.confirmButton.disabled = true;
    dom.confirmButton.textContent = "Подтвердить и отправить";
    window.QueueJournalUI?.render();
    return;
  }
  if (!queued.length) {
    const text = active.length
      ? `Выполняется задач: ${active.length}. Экран обновляется автоматически; после двух минут без событий появится предупреждение.`
      : "Новых задач для отправки нет. Ниже остаётся история выполнения и результаты.";
    showPlan(text, false);
  } else {
    const message = mode.kind==='manual' ? 'Ручной режим: скопируйте поручение кнопкой в записи ниже и вставьте в любую AI-оболочку. Доска не запускает его и не получает результат автоматически.'
      : mode.kind==='hermes' ? mode.allowed ? `К отправке в Hermes: ${queued.length} правок в ${getDispatchGroups(queued).length} запуск(ах). Проверьте рабочие папки и предупреждение о правах.` : 'Hermes CLI недоступен. Поручения сохранены. Проверьте установку или PROJECT_BOARD_HERMES_BIN.'
      : !mode.allowed ? "Текущий лимит недоступен или исчерпан. Поручения сохранены; отправка станет доступна после восстановления связи или сброса."
      : !sendable.length ? "Доступного лимита пока недостаточно даже для одного запуска. Уменьшите глубину следующего поручения или дождитесь сброса."
      : fits
      ? `К отправке: ${queued.length} правок в ${getDispatchGroups(queued).length} согласованных запуск(ах), ${points} плановых единиц при доступных ${available}%.`
      : `Очередь разбита на ${batches.length} безопасных пакета. Сейчас можно отправить пакет 1: ${sendable.length} правок, ${getPointTotal(sendable)} единиц.`;
    showPlan(message, mode.kind!=='manual' && (!fits || !mode.allowed));
  }
  dom.confirmButton.disabled = !sendable.length;
  dom.confirmButton.textContent = mode.kind==='manual' ? 'Автозапуск выключен' : fits ? `Подтвердить и отправить в ${mode.name}` : `Отправить пакет 1 из ${batches.length}`;
  if (window.QueueJournalUI) QueueJournalUI.render();
  else {
    dom.queueList.replaceChildren();
    state.queue.filter(item=>!item.archivedAt).forEach((item) => dom.queueList.append(createQueueItem(item)));
  }
}

function createEmptyState(text) {
  const element = document.createElement("div");
  element.className = "empty-state";
  element.textContent = text;
  return element;
}

function createQueueItem(item, { selection = "send" } = {}) {
  const meta = getMeta(item);
  const row = document.createElement("article");
  row.className = `queue-item queue-item--${meta.tone}`;
  if (item.isStale) row.classList.add("is-stale");

  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.setAttribute("aria-label", `Выбрать изменение ${item.projectName}`);
  checkbox.dataset.queueId = item.id;
  checkbox.dataset.queueAction = "send";
  checkbox.checked = item.status === "queued" && state.sendableQueueIds.has(item.id);
  checkbox.disabled = item.status !== "queued" || !state.sendableQueueIds.has(item.id);

  const content = document.createElement("div");
  content.className = "queue-content";
  const titleRow = document.createElement("div");
  titleRow.className = "queue-title-row";
  const title = document.createElement("strong");
  title.textContent = item.projectName;
  const badge = document.createElement("span");
  badge.className = `task-status task-status--${meta.tone}`;
  badge.textContent = meta.label;
  titleRow.append(title, badge);

  const description = document.createElement("p");
  description.textContent = `${kindLabels[item.kind]} · ${scopeLabels[item.scope]}: ${item.text}`;
  const modelStamp = document.createElement('small');
  modelStamp.className = 'queue-model';
  modelStamp.textContent = `Модель: ${typeof TaskModels!=='undefined' ? TaskModels.label(item) : item.modelLabel || item.model || 'Как в задаче'}`;
  const route = document.createElement("small");
  route.textContent = `Маршрут: ${item.route?.label || "готовится"}`;
  content.append(titleRow, description, modelStamp, route, createProgress(item, meta));
  if (item.archivedAt) {
    const stamp = document.createElement("small");
    stamp.className = "queue-archive-stamp";
    stamp.textContent = `В архиве с ${formatAt(item.archivedAt)}. Результат сохранён.`;
    content.append(stamp);
  }

  if (item.isStale) {
    const stale = document.createElement("p");
    stale.className = "task-notice task-notice--attention";
    stale.textContent = "Нет нового сигнала более двух минут. Проверьте исполнителя: задача может ждать решения или соединение могло прерваться. Это не повод автоматически запускать копию.";
    content.append(stale);
  }
  const detail = item.error || item.blockedReason || item.result || (item.status === "waiting-user" ? "В дашборде нельзя автоматически разрешать команды и доступы. Откройте связанный диалог Codex, примите решение и обновите экран." : "");
  if (detail) {
    const details = document.createElement("details");
    details.className = "task-details";
    const summary = document.createElement("summary");
    summary.textContent = item.result ? "Показать результат" : "Показать причину";
    const text = document.createElement("p");
    text.textContent = detail;
    details.append(summary, text);
    content.append(details);
  }
  const copyRequest=document.createElement('button');
  copyRequest.type='button';copyRequest.className='button button-small button-secondary';copyRequest.textContent='Скопировать поручение';
  copyRequest.addEventListener('click',()=>BoardUI.copy(HarnessMode.prompt(state.projects.find(p=>p.id===item.projectId)||{name:item.projectName},[item])));
  content.append(copyRequest);
  if (!item.archivedAt && ["waiting-busy", "failed", "interrupted"].includes(item.status) && HarnessMode.policy(state.dispatch || {},state.budget || {}).kind!=='manual') {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "button button-small button-secondary";
    retry.textContent = "Повторить отправку";
    retry.addEventListener("click", () => retryDispatch(item.id));
    content.append(retry);
  }
  if (selection === "send" && item.status === "queued" && !item.archivedAt) row.append(checkbox);
  row.append(content);
  return row;
}

function createProgress(item, meta) {
  const container = document.createElement("div");
  container.className = "task-progress";
  const heading = document.createElement("div");
  heading.className = "task-progress-heading";
  const stage = document.createElement("span");
  stage.textContent = item.progressStage || meta.label;
  const value = document.createElement("strong");
  value.textContent = `${meta.progress}%`;
  heading.append(stage, value);
  const progress = document.createElement("progress");
  progress.max = 100;
  progress.value = meta.progress;
  progress.setAttribute("aria-label", `Прогресс процесса: ${meta.progress}%`);
  const steps = document.createElement("ol");
  steps.className = "task-stepper";
  executionSteps.forEach((label, index) => {
    const step = document.createElement("li");
    step.textContent = label;
    if (index < meta.index) step.classList.add("is-complete");
    if (index === meta.index) step.classList.add("is-current");
    steps.append(step);
  });
  const updated = document.createElement("small");
  updated.className = "task-updated";
  updated.textContent = `Последний сигнал: ${formatAt(item.lastEventAt || item.completedAt || item.createdAt)}`;
  container.append(heading, progress, steps, updated);
  return container;
}

function showPlan(message, warning = false) {
  dom.planMessage.textContent = message;
  dom.planMessage.classList.toggle("is-warning", warning);
}

function renderActivity() {
  dom.activityList.replaceChildren();
  state.activity.slice(0, 8).forEach((item) => {
    const row = document.createElement("li");
    const time = document.createElement("time");
    const text = document.createElement("div");
    time.dateTime = item.at;
    time.textContent = formatAt(item.at);
    text.textContent = item.text;
    row.append(time, text);
    dom.activityList.append(row);
  });
}

function render() {
  renderBudget();
  renderTomorrowPlan();
  renderDispatchStatus();
  renderProjects();
  renderQueue();
  renderActivity();
}

async function queueUpdates(updates) {
  try {
    const result = await request("/api/queue", { method: "POST", body: JSON.stringify({ updates }) });
    state.queue.push(...(result.added || []));
    render();
    await loadState();
    return true;
  } catch (error) {
    showPlan(error.message, true);
    window.BoardUI?.toast(error.message, true);
    return false;
  }
}

async function retryDispatch(queueId) {
  try {
    const result = await request("/api/retry-dispatch", { method: "POST", body: JSON.stringify({ queueId }) });
    showPlan(result.message);
    await loadState();
  } catch (error) {
    showPlan(error.message, true);
  }
}

document.querySelector("#bulk-apply").addEventListener("click", async () => {
  const text = dom.bulkText.value.trim();
  if (!state.selected.size) return showPlan("Сначала выберите хотя бы один проект.", true);
  if (!text) return showPlan("Напишите общее изменение для выбранных проектов.", true);
  const updates = [...state.selected].map((projectId) => ({ projectId, kind: "comment", scope: dom.bulkScope.value, text }));
  const button = document.querySelector("#bulk-apply");
  button.disabled = true;
  try { if (await queueUpdates(updates)) { dom.bulkText.value = ""; window.BoardUI?.toast("Выбранные карточки заряжены. Запуск — кнопкой «Поехали»."); } }
  finally { button.disabled = false; }
});

dom.confirmButton.addEventListener("click", async () => {
  if (window.QueueJournalUI?.busy) return;
  const queueIds = window.QueueJournalUI ? QueueJournalUI.sendIds() : [...document.querySelectorAll('#queue-list input[data-queue-action="send"]:checked:not(:disabled)')].map((input) => input.dataset.queueId);
  if (!queueIds.length) return showPlan("Выберите новые задачи для подтверждения.", true);
  dom.confirmButton.disabled = true;
  const projectIds=state.queue.filter(q=>queueIds.includes(q.id)).map(q=>q.projectId);
  try {
    const result = await request("/api/confirm-dispatch", { method: "POST", body: JSON.stringify({ queueIds }) });
    showPlan(result.message);
    window.BoardUI?.toast(result.message);
    await loadState();
    if(window.BoardMotion){document.querySelectorAll('dialog[open]').forEach(d=>BoardUI.close(d));setTimeout(()=>BoardMotion.launch(projectIds),220);}
  } catch (error) {
    showPlan(error.message, true);
    window.BoardUI?.toast(error.message, true);
    await loadState({ quiet: true });
  }
});

document.querySelector("#refresh-button").addEventListener("click", () => loadState());

setInterval(() => {
  if (window.BoardDrag?.active || window.BoardUI?.saving) return;
  const hasActiveTasks = state.queue.some((item) => activeStatuses.has(item.status));
  const writing = document.activeElement?.matches("textarea, input, select");
  const budgetNeedsRefresh = Date.now() - state.lastLoadedAt >= 30_000;
  if ((hasActiveTasks || budgetNeedsRefresh) && document.visibilityState === "visible" && !writing) loadState({ quiet: true });
}, 5000);

async function loadBoard() {
  try {
    const data = await request("/api/board");
    if (!state.board || data.board.revision >= state.board.revision) {
      state.board = data.board;
      state.projects = data.projects;
      renderProjects();
      window.ProjectDetail?.restore();
    }
  } catch (error) { if (!state.board) window.BoardUI?.toast(`Доска не загружена: ${error.message}`, true); }
}
loadBoard();
loadState();
