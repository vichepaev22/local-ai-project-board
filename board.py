"""Small, revisioned planning board. Planning never dispatches Codex work."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from urllib.parse import urlparse

COLUMNS = [
    ("backlog", "Идеи"), ("sprint", "Этот спринт"),
    ("ready", "Готово к запуску"), ("doing", "В работе"),
    ("review", "Проверка"), ("done", "Завершено"),
]
COLORS = {"paper", "sand", "sage", "blue", "rose", "lilac"}


class BoardConflict(ValueError):
    pass


def normalize_board(saved: dict, projects: list[dict]) -> dict:
    board = copy.deepcopy(saved) if saved else {
        "revision": 0, "name": "Мои проекты", "sprint": "Фокус на ближайшую неделю",
        "discussionUrl": "", "theme": "warm", "cards": {},
        "columns": [{"id": key, "name": title, "cards": []} for key, title in COLUMNS],
    }
    ids = {p["id"] for p in projects}
    seen = set()
    for column in board["columns"]:
        column["cards"] = [pid for pid in column["cards"] if pid in ids and not (pid in seen or seen.add(pid))]
    colors = ["sand", "blue", "sage", "paper", "rose", "sage", "lilac", "paper", "sand", "blue"]
    for index, project in enumerate(projects):
        pid = project["id"]
        if pid not in seen:
            target = "backlog"
            next(c for c in board["columns"] if c["id"] == target)["cards"].append(pid)
        board["cards"].setdefault(pid, {
            "title": "", "color": colors[index % len(colors)],
            "important": False,
            "urgent": False, "due": "", "discussionUrl": "", "notes": "",
        })
    return board


def audit_change(before: dict, after: dict, payload: dict) -> None:
    """Keep the audit in the same atomic document as the board mutation."""
    pid, op = payload.get("projectId"), payload.get("op")
    changes, title = [], ""
    if op == "move":
        old = next(c for c in before["columns"] if pid in c["cards"])
        new = next(c for c in after["columns"] if pid in c["cards"])
        if old["id"] != new["id"]:
            title = "Перемещение карточки"
            changes = [{"field": "Колонка", "before": old["name"], "after": new["name"]}]
        elif old["cards"].index(pid) != new["cards"].index(pid):
            title = "Изменён порядок в колонке"
            changes = [{"field": new["name"], "before": old["cards"].index(pid)+1, "after": new["cards"].index(pid)+1}]
    elif op == "card":
        labels = {"title":"Название", "notes":"Заметка", "color":"Цвет", "due":"Срок", "important":"Важно", "urgent":"Срочно", "discussionUrl":"Обсуждение"}
        changes = [{"field":labels[key], "before":before["cards"][pid].get(key), "after":value}
                   for key, value in after["cards"][pid].items()
                   if key in labels and before["cards"][pid].get(key) != value]
        title = "Изменена карточка"
    elif op == "rename-column":
        old = next(c for c in before["columns"] if c["id"] == payload["columnId"])
        new = next(c for c in after["columns"] if c["id"] == old["id"])
        if old["name"] != new["name"]:
            title = "Переименована колонка"
            changes = [{"field":"Колонка", "before":old["name"], "after":new["name"]}]
            for card_id in old["cards"]:
                after.setdefault("history", []).append({"at":datetime.now(timezone.utc).isoformat(), "projectId":card_id, "title":title, "changes":changes})
        return
    if changes:
        after.setdefault("history", []).append({"at":datetime.now(timezone.utc).isoformat(), "projectId":pid, "title":title, "changes":changes})


def chat_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2000:
        raise ValueError("Ссылка слишком длинная или неверного формата.")
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"chatgpt.com", "chat.openai.com"} or parsed.username or parsed.password or parsed.port:
        raise ValueError("Укажите HTTPS-ссылку на чат или общий проект ChatGPT.")
    return value


def apply_operation(board: dict, payload: dict) -> dict:
    if type(payload.get("revision")) is not int or payload["revision"] != board["revision"]:
        raise BoardConflict("Доска уже изменилась в другом окне. Данные обновлены; повторите изменение.")
    result = copy.deepcopy(board)
    op = payload.get("op")
    if op == "move":
        pid, target, before = payload.get("projectId"), payload.get("columnId"), payload.get("beforeId")
        if pid not in result["cards"] or target not in {c["id"] for c in result["columns"]}:
            raise ValueError("Карточка или колонка не найдена.")
        column = next(c for c in result["columns"] if c["id"] == target)
        if before == pid:
            return result
        if before is not None and before not in column["cards"]:
            raise ValueError("Позиция карточки устарела. Обновите доску.")
        for c in result["columns"]:
            c["cards"] = [value for value in c["cards"] if value != pid]
        index = column["cards"].index(before) if before else len(column["cards"])
        column["cards"].insert(index, pid)
    elif op == "card":
        card = result["cards"].get(payload.get("projectId"))
        if card is None:
            raise ValueError("Карточка не найдена.")
        changes = payload.get("changes")
        if not isinstance(changes, dict):
            raise ValueError("Не указаны изменения.")
        for key, value in changes.items():
            if key in {"important", "urgent"} and type(value) is bool:
                card[key] = value
            elif key == "color" and value in COLORS:
                card[key] = value
            elif key in {"title", "notes", "due"} and isinstance(value, str):
                limits = {"title": 160, "notes": 4000, "due": 10}
                if len(value) > limits[key]:
                    raise ValueError("Слишком длинное поле карточки.")
                if key == "due" and value:
                    from datetime import date
                    date.fromisoformat(value)
                card[key] = value.strip()
            elif key == "discussionUrl":
                card[key] = chat_url(value)
            else:
                raise ValueError("Недопустимое поле карточки.")
    elif op == "settings":
        for key in ("name", "sprint"):
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise ValueError("Название и фокус должны содержать от 1 до 200 символов.")
            result[key] = value.strip()
        if payload.get("theme") not in {"warm", "forest"}:
            raise ValueError("Неизвестное оформление.")
        result["theme"] = payload["theme"]
        result["discussionUrl"] = chat_url(payload.get("discussionUrl", ""))
    elif op == "rename-column":
        column = next((c for c in result["columns"] if c["id"] == payload.get("columnId")), None)
        name = payload.get("name")
        if column is None or not isinstance(name, str) or not name.strip() or len(name) > 50:
            raise ValueError("Укажите название колонки до 50 символов.")
        column["name"] = name.strip()
    else:
        raise ValueError("Неизвестное действие доски.")
    audit_change(board, result, payload)
    result["revision"] += 1
    return result
