"""Save/load JSON và replay theo seed. Load = dựng lại từ seed + danh sách action rồi so khớp snapshot."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .engine import Engine
from .models import SEATS, action_from_dict
from .rules.base import RuleConfig
from .rules.training import TableRuleset

SCHEMA_VERSION = 1
MAX_SAVE_BYTES = 5 * 1024 * 1024
MAX_ACTIONS = 5000
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class SaveError(ValueError):
    pass


def safe_save_path(name: str, save_dir: Path) -> Path:
    """Chỉ cho phép tên file đơn giản, luôn nằm trong thư mục save."""
    name = name.strip()
    if not name.endswith(".json"):
        name += ".json"
    if not _NAME_RE.match(name) or name.startswith(".") or ".." in name:
        raise SaveError("Tên file chỉ gồm chữ, số, '_', '-', '.' (tối đa 64 ký tự), không chứa đường dẫn.")
    base = save_dir.resolve()
    path = (base / name).resolve()
    if path.parent != base:
        raise SaveError("Chỉ được ghi file trong thư mục save.")
    return path


def to_payload(engine: Engine, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    s = engine.state
    return {
        "schema_version": SCHEMA_VERSION,
        "game": "tusac-terminal",
        "seed": s.seed,
        "dealer": s.dealer,
        "rules": engine.rules.config.to_dict(),
        "meta": meta or {},
        "actions": list(engine.action_log),
        "state": s.to_dict(),
    }


def save_game(engine: Engine, path: Path, meta: dict[str, Any] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(to_payload(engine, meta), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def replay(seed: int, rules: TableRuleset, dealer: str, actions: list[dict[str, Any]]) -> Engine:
    """Chạy lại cùng seed + danh sách action. Action bị luật từ chối → lỗi."""
    engine = Engine.new_game(seed, rules, dealer)
    for n, raw in enumerate(actions, 1):
        action = action_from_dict(raw)
        result = engine.apply(action)
        if not result.allowed:
            raise SaveError(f"Action #{n} ({raw}) bị từ chối khi replay: {result.message}")
    return engine


def load_payload(payload: Any) -> tuple[Engine, dict[str, Any]]:
    if not isinstance(payload, dict):
        raise SaveError("File save không đúng định dạng.")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SaveError(f"schema_version {version!r} không được hỗ trợ (cần {SCHEMA_VERSION}).")
    seed, dealer, actions = payload.get("seed"), payload.get("dealer"), payload.get("actions")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise SaveError("seed không hợp lệ.")
    if dealer not in SEATS:
        raise SaveError("dealer không hợp lệ.")
    if not isinstance(actions, list) or len(actions) > MAX_ACTIONS:
        raise SaveError("actions không hợp lệ.")
    try:
        rules = TableRuleset(RuleConfig.from_mapping(payload.get("rules") or {}))
        engine = replay(seed, rules, dealer, actions)
    except (ValueError, TypeError) as exc:
        raise SaveError(f"Không khôi phục được ván: {exc}") from exc
    if engine.state.to_dict() != payload.get("state"):
        raise SaveError("Trạng thái sau replay KHÔNG khớp snapshot đã lưu (file bị sửa hoặc khác phiên bản).")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    return engine, meta


def load_game(path: Path) -> tuple[Engine, dict[str, Any]]:
    if not path.is_file():
        raise SaveError(f"Không tìm thấy file {path}")
    if path.stat().st_size > MAX_SAVE_BYTES:
        raise SaveError("File save quá lớn.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SaveError(f"File JSON hỏng: {exc}") from exc
    return load_payload(payload)
