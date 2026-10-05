"""Create and expose portable, local-only runtime data paths.

The initializer deliberately uses exclusive creation.  A partially edited or
corrupt user file is evidence that belongs to the user, not an invitation for a
launcher to replace it with defaults.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PROJECTS_FILE = DATA / "projects.json"
BUDGET_FILE = DATA / "budget.json"
QUEUE_FILE = DATA / "queue.json"
ACTIVITY_FILE = DATA / "activity.json"
EVENTS_FILE = DATA / "dispatch-events.jsonl"
TOMORROW_FILE = DATA / "tomorrow-plan.json"
BOARD_FILE = DATA / "board.json"

FILE_NAMES = {
    "PROJECTS_FILE": "projects.json",
    "BUDGET_FILE": "budget.json",
    "QUEUE_FILE": "queue.json",
    "ACTIVITY_FILE": "activity.json",
    "EVENTS_FILE": "dispatch-events.jsonl",
    "TOMORROW_FILE": "tomorrow-plan.json",
    "BOARD_FILE": "board.json",
}


def _unknown_budget() -> dict[str, Any]:
    return {
        "isLive": False,
        "limitEnforced": False,
        "dispatchAllowed": False,
        "capturedAt": None,
        "note": "Лимиты неизвестны: локальная доска ещё не подключена к провайдеру.",
        "fiveHour": {"remainingPercent": None, "resetsAt": None},
        "weekly": {"remainingPercent": None, "resetsAt": None},
    }


def _defaults() -> dict[str, Any]:
    return {
        "PROJECTS_FILE": [],
        "BUDGET_FILE": _unknown_budget(),
        "QUEUE_FILE": [],
        "ACTIVITY_FILE": [],
        "EVENTS_FILE": None,
        "TOMORROW_FILE": {"title": "План на завтра", "tasks": []},
        "BOARD_FILE": {},
    }


def _create_missing(path: Path, value: Any) -> None:
    """Create exactly one missing file, leaving all existing bytes untouched."""
    try:
        with path.open("x", encoding="utf-8", newline="\n") as file:
            if value is not None:
                json.dump(value, file, ensure_ascii=False, indent=2)
                file.write("\n")
    except FileExistsError:
        return


def initialize_data(data_dir: Path) -> dict[str, Path]:
    """Initialize *only* absent files and return the selected global paths."""
    global DATA, PROJECTS_FILE, BUDGET_FILE, QUEUE_FILE, ACTIVITY_FILE
    global EVENTS_FILE, TOMORROW_FILE, BOARD_FILE

    DATA = Path(data_dir).expanduser().resolve()
    DATA.mkdir(parents=True, exist_ok=True)
    paths = {name: DATA / filename for name, filename in FILE_NAMES.items()}
    for name, value in _defaults().items():
        _create_missing(paths[name], value)

    PROJECTS_FILE = paths["PROJECTS_FILE"]
    BUDGET_FILE = paths["BUDGET_FILE"]
    QUEUE_FILE = paths["QUEUE_FILE"]
    ACTIVITY_FILE = paths["ACTIVITY_FILE"]
    EVENTS_FILE = paths["EVENTS_FILE"]
    TOMORROW_FILE = paths["TOMORROW_FILE"]
    BOARD_FILE = paths["BOARD_FILE"]
    return {"DATA": DATA, **paths}
