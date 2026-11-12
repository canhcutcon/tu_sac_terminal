"""Nạp rule profile theo tên hoặc đường dẫn file YAML."""
from __future__ import annotations

from pathlib import Path

from ..config import load_flat_yaml
from .base import ClaimOption, RuleConfig, Ruleset, ScoreResult
from .training import TableRuleset

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"

PROFILE_FILES = {
    "training_basic": "rules.training.yaml",
    "family_nhatrang": "rules.family_nhatrang.yaml",
}
UNVERIFIED_PROFILES = {
    "reference_vinagames": (
        "Profile reference_vinagames chưa được triển khai: cần chép và kiểm tra từng điều kiện/ngoại lệ "
        "từ hướng dẫn Vinagames kèm unit test trước khi bật (xem mục 6.1 của đặc tả)."
    ),
}


def load_ruleset(name_or_path: str = "training_basic") -> TableRuleset:
    if name_or_path in UNVERIFIED_PROFILES:
        raise ValueError(UNVERIFIED_PROFILES[name_or_path])
    if name_or_path in PROFILE_FILES:
        path = CONFIG_DIR / PROFILE_FILES[name_or_path]
        if not path.exists():
            if name_or_path == "training_basic":
                return TableRuleset(RuleConfig())
            raise ValueError(f"Không tìm thấy file profile {path}")
    else:
        path = Path(name_or_path)
        if path.suffix not in (".yaml", ".yml") or not path.is_file():
            known = ", ".join(PROFILE_FILES)
            raise ValueError(f"Không biết profile {name_or_path!r}. Dùng một trong: {known} hoặc đường dẫn .yaml")
    data = load_flat_yaml(path)
    return TableRuleset(RuleConfig.from_mapping(data))


__all__ = ["ClaimOption", "RuleConfig", "Ruleset", "ScoreResult", "TableRuleset", "load_ruleset"]
