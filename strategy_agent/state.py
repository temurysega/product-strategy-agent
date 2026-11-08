"""Atomic project checkpoints and a process lock shared by all CLI commands."""
from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Project:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.root = self.path
        self.state_file = self.path / "state" / "state.json"

    def safe_path(self, relative):
        supplied = Path(relative)
        if supplied.is_absolute() or ".." in supplied.parts:
            raise ValueError("Путь должен оставаться внутри проекта.")
        current = self.path
        for part in supplied.parts:
            current /= part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise ValueError("Ссылки и junction в хранилище проекта запрещены.")
        if not current.resolve().is_relative_to(self.path):
            raise ValueError("Выход за пределы проекта запрещён.")
        return current

    def initialize(self, brief, budget=2.0):
        if self.state_file.exists():
            raise ValueError("Проект уже существует. Используйте resume или другую папку.")
        if not isinstance(brief, str) or not brief.strip():
            raise ValueError("Нужен непустой бриф.")
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not math.isfinite(budget) or budget <= 0:
            raise ValueError("Бюджет должен быть положительным конечным числом.")
        for folder in ("materials", "artifacts", "state"):
            self.safe_path(folder).mkdir(parents=True, exist_ok=True)
        state = {"schema_version": 1, "id": uuid.uuid4().hex, "created_at": now(),
                 "updated_at": now(), "status": "ready", "brief": brief.strip(),
                 "budget_usd": budget, "total_cost_usd": 0.0, "unknown_cost_requests": 0,
                 "ledger": [], "steps": 0, "pending": None, "model_errors": 0,
                 "question": None, "decision": None}
        self.save(state)
        self.write("state/messages.json", [{"role": "user", "content": brief.strip()}])
        self.event("initialized", {"budget_usd": budget})
        return state

    @property
    def state(self):
        if not self.state_file.is_file():
            raise ValueError("Проект не создан. Сначала выполните init.")
        result = self.read("state/state.json")
        if result.get("schema_version") != 1:
            raise ValueError("Неизвестная версия состояния проекта.")
        return result

    def save(self, state):
        state["updated_at"] = now()
        write_json(self.safe_path("state/state.json"), state)

    def read(self, relative, default=None):
        path = self.safe_path(relative)
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def write(self, relative, value):
        write_json(self.safe_path(relative), value)

    def event(self, kind, details=None):
        event = {"at": now(), "event": kind, "details": details or {}}
        path = self.safe_path("state/events.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n")
            stream.flush()
        return event

    def request_pause(self):
        self.write("state/control.json", {"pause": True, "at": now()})

    def pause_requested(self):
        return bool((self.read("state/control.json", {}) or {}).get("pause"))

    def clear_pause(self):
        self.write("state/control.json", {"pause": False, "at": now()})

    @contextmanager
    def lock(self):
        directory = self.safe_path("state")
        directory.mkdir(parents=True, exist_ok=True)
        with self.safe_path("state/run.lock").open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                raise ValueError("Проект уже обрабатывает другой процесс. pause доступен отдельно.") from None
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_UN)
