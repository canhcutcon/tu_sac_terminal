"""Giao diện Ruleset và cấu hình luật bàn (rule profile)."""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ..melds import MeldRules
from ..models import Claim, GameState, MeldKind, RuleResult

CLAIM_KIND_NAMES: tuple[str, ...] = tuple(k.value for k in MeldKind)

_CHOICES: dict[str, tuple[str, ...]] = {
    "khap_exposure": ("confirm_before_apply", "auto"),
    "no_increase_trash": ("off", "warn_only", "enforce"),
    "penalty_mode": ("disabled",),
    "priority_policy": ("explicit_order",),
    "stock_empty": ("draw_game",),
}

# Giải thích từng tùy chọn — dùng cho lệnh `rules`.
OPTION_HELP: dict[str, str] = {
    "ruleset": "Tên profile luật đang dùng.",
    "allow_pawn_multicolor_trio": "Cho phép bộ 3 Tốt khác màu.",
    "allow_pawn_multicolor_quad": "Cho phép bộ 4 Tốt đủ 4 màu.",
    "lone_general_ok": "Tướng đứng một mình không bị tính là rác.",
    "pairs_count_as_meld": "Đôi được tính là phe khi xét rác / tới.",
    "mandatory_pair_claim": "Đang giữ đôi mà quân thứ ba xuất hiện thì BẮT BUỘC ăn thành khạp.",
    "khap_exposure": "confirm_before_apply: khui quàn phải tự xác nhận; auto: bắt buộc khui khi có quân thứ tư.",
    "forbid_split_khap": "Cấm đánh lẻ quân thuộc khạp/quàn đang giữ trên tay.",
    "no_increase_trash": "Ăn mà làm tăng rác: off (bỏ qua) / warn_only (cảnh báo) / enforce (cấm).",
    "penalty_mode": "Phạt/đền: hiện chỉ có 'disabled' (chưa xác minh luật đền).",
    "priority_policy": "explicit_order: Tới > Quàn > Khạp > bộ khác; hòa thì nhà gần người đánh hơn.",
    "win_any_seat": "Nhà bất kỳ được ăn quân để tới (không cần là nhà kế tiếp).",
    "claim_next_seat_kinds": "Các bộ nhà kế tiếp (hoặc người tự bốc) được ăn.",
    "claim_any_seat_kinds": "Các bộ nhà bất kỳ được ăn (ngoài lượt).",
    "stock_empty": "Hết nọc mà chưa ai tới: draw_game = hòa ván.",
}


@dataclass(frozen=True)
class RuleConfig:
    ruleset: str = "training_basic"
    allow_pawn_multicolor_trio: bool = True
    allow_pawn_multicolor_quad: bool = True
    lone_general_ok: bool = True
    pairs_count_as_meld: bool = True
    mandatory_pair_claim: bool = False
    khap_exposure: str = "confirm_before_apply"
    forbid_split_khap: bool = False
    no_increase_trash: str = "warn_only"
    penalty_mode: str = "disabled"
    priority_policy: str = "explicit_order"
    win_any_seat: bool = True
    claim_next_seat_kinds: tuple[str, ...] = CLAIM_KIND_NAMES
    claim_any_seat_kinds: tuple[str, ...] = ("triplet", "quad")
    stock_empty: str = "draw_game"

    def __post_init__(self) -> None:
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if f.type in ("bool", bool) and not isinstance(value, bool):
                raise ValueError(f"{f.name} phải là true/false, nhận {value!r}")
        if not isinstance(self.ruleset, str) or not self.ruleset:
            raise ValueError("ruleset phải là chuỗi khác rỗng")
        for key, choices in _CHOICES.items():
            if getattr(self, key) not in choices:
                raise ValueError(f"{key} phải là một trong {choices}, nhận {getattr(self, key)!r}")
        for key in ("claim_next_seat_kinds", "claim_any_seat_kinds"):
            for kind in getattr(self, key):
                if kind not in CLAIM_KIND_NAMES:
                    raise ValueError(f"{key}: loại bộ không hợp lệ {kind!r}; hợp lệ: {CLAIM_KIND_NAMES}")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> RuleConfig:
        names = {f.name for f in dataclasses.fields(cls)}
        unknown = set(data) - names
        if unknown:
            raise ValueError(f"Tùy chọn luật không được hỗ trợ: {sorted(unknown)}")
        kwargs: dict[str, object] = {}
        for key, value in data.items():
            if key in ("claim_next_seat_kinds", "claim_any_seat_kinds"):
                if isinstance(value, str):
                    value = [p.strip() for p in value.split(",") if p.strip()]
                if not isinstance(value, (list, tuple)):
                    raise ValueError(f"{key} phải là danh sách")
                value = tuple(str(v) for v in value)
            kwargs[key] = value
        return cls(**kwargs)  # type: ignore[arg-type]

    def to_dict(self) -> dict[str, object]:
        return {f.name: (list(v) if isinstance(v := getattr(self, f.name), tuple) else v) for f in dataclasses.fields(self)}

    def meld_rules(self) -> MeldRules:
        return MeldRules(
            pawn_trio=self.allow_pawn_multicolor_trio,
            pawn_quad=self.allow_pawn_multicolor_quad,
            lone_general_ok=self.lone_general_ok,
            pairs_ok=self.pairs_count_as_meld,
        )


@dataclass(frozen=True)
class ClaimOption:
    """Ba kết quả tách biệt: có thể tạo bộ (can_form) / được ăn (allowed) / bắt buộc ăn (mandatory)."""

    claim: Claim
    can_form: bool
    allowed: bool
    mandatory: bool
    wins: bool
    trash_before: int
    trash_after: int  # sau khi ăn và đánh đi một quân rác (0 nếu tới)
    reason_code: str
    message: str
    warning: str = ""

    def as_result(self) -> RuleResult:
        msg = self.message + (f" Cảnh báo: {self.warning}" if self.warning else "")
        return RuleResult(self.allowed, self.mandatory, self.reason_code, msg)


@dataclass(frozen=True)
class ScoreResult:
    points: dict[str, int]
    summary: str


class Ruleset(Protocol):
    config: RuleConfig

    def legal_claims(self, state: GameState, seat: str, card_id: str) -> list[Claim]: ...
    def claim_priority(self, state: GameState, claims: list[Claim]) -> Claim | None: ...
    def mandatory_claims(self, state: GameState, seat: str, card_id: str) -> list[Claim]: ...
    def legal_discards(self, state: GameState, seat: str) -> list[str]: ...
    def is_win(self, state: GameState, seat: str) -> bool: ...
    def score_round(self, state: GameState) -> ScoreResult: ...
