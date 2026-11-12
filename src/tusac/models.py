"""Mô hình dữ liệu cốt lõi của Tứ Sắc: Card, Meld, Action, RuleResult, GameState."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any, Union


class Color(IntEnum):
    RED = 0
    GREEN = 1
    YELLOW = 2
    WHITE = 3


class Rank(IntEnum):
    GENERAL = 0
    ADVISOR = 1
    ELEPHANT = 2
    CHARIOT = 3
    CANNON = 4
    HORSE = 5
    PAWN = 6


COLOR_VI = {Color.RED: "Đỏ", Color.GREEN: "Xanh", Color.YELLOW: "Vàng", Color.WHITE: "Trắng"}
RANK_VI = {
    Rank.GENERAL: "Tướng",
    Rank.ADVISOR: "Sĩ",
    Rank.ELEPHANT: "Tượng",
    Rank.CHARIOT: "Xe",
    Rank.CANNON: "Pháo",
    Rank.HORSE: "Mã",
    Rank.PAWN: "Tốt",
}
# Chữ Hán theo kiểu in truyền thống: Đỏ/Vàng dùng một bộ chữ, Trắng/Xanh dùng bộ chữ còn lại.
HAN_RED_YELLOW = {
    Rank.GENERAL: "帥",
    Rank.ADVISOR: "仕",
    Rank.ELEPHANT: "相",
    Rank.CHARIOT: "俥",
    Rank.CANNON: "炮",
    Rank.HORSE: "傌",
    Rank.PAWN: "卒",
}
HAN_WHITE_GREEN = {
    Rank.GENERAL: "將",
    Rank.ADVISOR: "士",
    Rank.ELEPHANT: "象",
    Rank.CHARIOT: "車",
    Rank.CANNON: "包",
    Rank.HORSE: "馬",
    Rank.PAWN: "兵",
}


def han(color: Color, rank: Rank) -> str:
    table = HAN_RED_YELLOW if color in (Color.RED, Color.YELLOW) else HAN_WHITE_GREEN
    return table[rank]

SEATS: tuple[str, ...] = ("A", "B", "C", "D")
COPIES = 4
DECK_SIZE = len(Color) * len(Rank) * COPIES  # 112
DEALER_HAND = 21
OTHER_HAND = 20
STOCK_SIZE = DECK_SIZE - DEALER_HAND - 3 * OTHER_HAND  # 31


def seat_index(seat: str) -> int:
    if seat not in SEATS:
        raise ValueError(f"Vị trí không hợp lệ: {seat!r}")
    return SEATS.index(seat)


def next_seat(seat: str, step: int = 1) -> str:
    return SEATS[(seat_index(seat) + step) % len(SEATS)]


def seat_distance(frm: str, to: str) -> int:
    """Số bước theo chiều chơi từ `frm` tới `to` (0..3)."""
    return (seat_index(to) - seat_index(frm)) % len(SEATS)


@dataclass(frozen=True, order=True)
class Card:
    color: Color
    rank: Rank
    copy_index: int

    @property
    def id(self) -> str:
        return f"{self.color.name}-{self.rank.name}-{self.copy_index}"

    @property
    def kind(self) -> tuple[Color, Rank]:
        return (self.color, self.rank)

    @property
    def cell(self) -> int:
        return int(self.color) * len(Rank) + int(self.rank)

    def name_vi(self) -> str:
        return f"{RANK_VI[self.rank]} {COLOR_VI[self.color].lower()}"

    @classmethod
    def from_id(cls, card_id: str) -> Card:
        try:
            color_s, rank_s, idx_s = card_id.split("-")
            card = cls(Color[color_s], Rank[rank_s], int(idx_s))
        except (KeyError, ValueError, AttributeError):
            raise ValueError(f"ID quân không hợp lệ: {card_id!r}") from None
        if not 0 <= card.copy_index < COPIES:
            raise ValueError(f"ID quân không hợp lệ: {card_id!r}")
        return card


class MeldKind(str, Enum):
    PAIR = "pair"
    TRIPLET = "triplet"
    QUAD = "quad"
    ODD_GAE = "odd_gae"
    ODD_CCH = "odd_cch"
    PAWN_TRIO = "pawn_trio"
    PAWN_QUAD = "pawn_quad"


MELD_VI = {
    MeldKind.PAIR: "Đôi",
    MeldKind.TRIPLET: "Khạp",
    MeldKind.QUAD: "Quàn",
    MeldKind.ODD_GAE: "Tướng-Sĩ-Tượng",
    MeldKind.ODD_CCH: "Xe-Pháo-Mã",
    MeldKind.PAWN_TRIO: "Tốt ba màu",
    MeldKind.PAWN_QUAD: "Tốt bốn màu",
}


class Phase(str, Enum):
    SETUP = "SETUP"
    DEAL = "DEAL"
    TURN_START = "TURN_START"
    DISCARD = "DISCARD"
    CLAIM_WINDOW = "CLAIM_WINDOW"
    RESOLVE_CLAIMS = "RESOLVE_CLAIMS"
    DRAW_FROM_STOCK = "DRAW_FROM_STOCK"
    EVALUATE = "EVALUATE"
    WIN_CHECK = "WIN_CHECK"
    ROUND_END = "ROUND_END"


PHASE_VI = {
    Phase.SETUP: "chuẩn bị",
    Phase.DEAL: "chia bài",
    Phase.TURN_START: "bắt đầu lượt",
    Phase.DISCARD: "đánh bài",
    Phase.CLAIM_WINDOW: "chờ quyền ăn",
    Phase.RESOLVE_CLAIMS: "phân xử",
    Phase.DRAW_FROM_STOCK: "bốc nọc",
    Phase.EVALUATE: "xét quân vừa bốc",
    Phase.WIN_CHECK: "xét tới",
    Phase.ROUND_END: "hết ván",
}


@dataclass
class Meld:
    kind: MeldKind
    card_ids: list[str]
    provenance: str  # "dealt": phần trên tay có sẵn từ lúc chia; "formed": hình thành về sau
    claimed_card_id: str | None = None
    source_seat: str | None = None
    origin: str | None = None  # "discard" | "draw"


@dataclass
class DiscardEvent:
    card_id: str
    seat: str
    turn_no: int
    origin: str  # "discard" | "draw"


@dataclass
class Event:
    turn_no: int
    seat: str | None
    kind: str
    text: str
    card_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- Actions


@dataclass(frozen=True)
class Discard:
    seat: str
    card_id: str


@dataclass(frozen=True)
class Claim:
    seat: str
    card_ids: tuple[str, ...]  # quân trên tay dùng để ghép (không gồm quân đang chờ)
    kind: MeldKind


@dataclass(frozen=True)
class Pass:
    seat: str


@dataclass(frozen=True)
class Draw:
    seat: str


Action = Union[Discard, Claim, Pass, Draw]


def action_to_dict(action: Action) -> dict[str, Any]:
    if isinstance(action, Discard):
        return {"type": "discard", "seat": action.seat, "card_id": action.card_id}
    if isinstance(action, Claim):
        return {
            "type": "claim",
            "seat": action.seat,
            "card_ids": list(action.card_ids),
            "kind": action.kind.value,
        }
    if isinstance(action, Pass):
        return {"type": "pass", "seat": action.seat}
    if isinstance(action, Draw):
        return {"type": "draw", "seat": action.seat}
    raise TypeError(f"Action không hợp lệ: {action!r}")


def action_from_dict(data: Any) -> Action:
    if not isinstance(data, dict):
        raise ValueError("Action phải là object JSON")
    kind = data.get("type")
    seat = data.get("seat")
    if seat not in SEATS:
        raise ValueError(f"Seat không hợp lệ trong action: {seat!r}")
    if kind == "discard":
        card_id = data.get("card_id")
        if not isinstance(card_id, str):
            raise ValueError("discard thiếu card_id")
        Card.from_id(card_id)
        return Discard(seat, card_id)
    if kind == "claim":
        ids = data.get("card_ids")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) > 3:
            raise ValueError("claim.card_ids không hợp lệ")
        for i in ids:
            Card.from_id(i)
        return Claim(seat, tuple(ids), MeldKind(data.get("kind")))
    if kind == "pass":
        return Pass(seat)
    if kind == "draw":
        return Draw(seat)
    raise ValueError(f"Loại action không hợp lệ: {kind!r}")


@dataclass(frozen=True)
class RuleResult:
    allowed: bool
    mandatory: bool = False
    reason_code: str = ""
    message: str = ""


# ---------------------------------------------------------------- State


def _plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


@dataclass
class GameState:
    seed: int
    ruleset_id: str
    dealer: str
    phase: Phase = Phase.SETUP
    current_seat: str = ""
    hands: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SEATS})
    initial_hands: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SEATS})
    stock: list[str] = field(default_factory=list)
    discard_pile: list[DiscardEvent] = field(default_factory=list)
    exposed_melds: dict[str, list[Meld]] = field(default_factory=lambda: {s: [] for s in SEATS})
    pending_card_id: str | None = None
    pending_from: str | None = None
    pending_origin: str | None = None
    claims: dict[str, Claim | None] = field(default_factory=dict)
    awaiting: list[str] = field(default_factory=list)
    history: list[Event] = field(default_factory=list)
    winner: str | None = None
    end_reason: str = ""
    scores: dict[str, int] = field(default_factory=dict)
    turn_no: int = 0

    def to_dict(self) -> dict[str, Any]:
        return _plain(self)
