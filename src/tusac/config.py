"""Bộ đọc YAML phẳng tối giản (key: value) cho file luật — không cần PyYAML, không eval."""
from __future__ import annotations

import re
from pathlib import Path

_KEY_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
MAX_CONFIG_BYTES = 64 * 1024


def _scalar(raw: str) -> object:
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


def parse_flat_yaml(text: str) -> dict[str, object]:
    """Hỗ trợ: `key: value`, bool, int, chuỗi, danh sách `[a, b]`, comment `#`."""
    data: dict[str, object] = {}
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        if ":" not in stripped:
            raise ValueError(f"Dòng {lineno}: thiếu dấu ':' — {line!r}")
        key, value = stripped.split(":", 1)
        key = key.strip()
        if not _KEY_RE.match(key):
            raise ValueError(f"Dòng {lineno}: khóa không hợp lệ {key!r}")
        if key in data:
            raise ValueError(f"Dòng {lineno}: khóa {key!r} bị lặp")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            data[key] = [str(_scalar(p)) for p in inner.split(",") if p.strip()] if inner else []
        else:
            data[key] = _scalar(value)
    return data


def load_flat_yaml(path: Path) -> dict[str, object]:
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError(f"File cấu hình quá lớn: {path}")
    return parse_flat_yaml(path.read_text(encoding="utf-8"))
