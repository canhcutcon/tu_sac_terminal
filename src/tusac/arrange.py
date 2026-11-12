"""Xếp bài trên tay người chơi: theo màu / theo loại / theo phe / tự xếp (move, swap).

Chỉ ảnh hưởng cách hiển thị và số thứ tự quân — không đụng tới trạng thái ván.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .deck import card, cards, sort_ids
from .engine import Engine
from .melds import analyze
from .models import COLOR_VI, MELD_VI, RANK_VI, Color, MeldKind, Rank
from .trainer import group_label

MODES = ("color", "rank", "meld", "free")
MODE_VI = {
    "color": "theo màu",
    "rank": "theo loại quân",
    "meld": "theo phe (rác để cuối)",
    "free": "tự do",
}
_COLOR_STYLE = {Color.RED: "bold red", Color.GREEN: "bold green", Color.YELLOW: "bold yellow", Color.WHITE: "bold bright_white"}

Row = tuple[str, str, list[str]]


@dataclass
class HandArrangement:
    mode: str = "color"
    custom: list[str] = field(default_factory=list)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Kiểu xếp không hợp lệ: {mode!r} (chọn {', '.join(MODES[:3])})")
        self.mode = mode

    def _sync(self, hand: list[str]) -> list[str]:
        """Giữ thứ tự tự xếp; bỏ quân đã rời tay, thêm quân mới vào cuối."""
        present = set(hand)
        keep = [i for i in self.custom if i in present]
        kept = set(keep)
        self.custom = keep + sort_ids(i for i in hand if i not in kept)
        return self.custom

    def rows(self, engine: Engine, seat: str) -> list[Row]:
        hand = list(engine.state.hands[seat])
        if self.mode == "color":
            ordered = sort_ids(hand)
            return [
                (COLOR_VI[c].upper(), _COLOR_STYLE[c], [i for i in ordered if card(i).color == c])
                for c in Color
            ]
        if self.mode == "rank":
            ordered = sorted(hand, key=lambda i: (card(i).rank, card(i).color, card(i).copy_index))
            return [(RANK_VI[r].upper(), "bold", [i for i in ordered if card(i).rank == r]) for r in Rank]
        if self.mode == "meld":
            a = analyze(cards(hand), engine.rules.meld_rules)
            rows: list[Row] = []
            for label, cs in a.groups:
                ids = [c.id for c in cs]
                pawn = label in (MeldKind.PAWN_TRIO.value, MeldKind.PAWN_QUAD.value)
                rows.append((group_label(label), "bold magenta" if pawn else _COLOR_STYLE[cs[0].color], ids))
            rows.append((f"RÁC ({a.trash_count})", "bold red", [c.id for c in a.trash]))
            return rows
        return [("TAY", "bold", list(self._sync(hand)))]

    def order(self, engine: Engine, seat: str) -> list[str]:
        return [cid for _, _, ids in self.rows(engine, seat) for cid in ids]

    def _to_free(self, engine: Engine, seat: str) -> list[str]:
        self.custom = self.order(engine, seat)
        self.mode = "free"
        return self.custom

    def move(self, engine: Engine, seat: str, src: int, dst: int) -> str:
        order = self._to_free(engine, seat)
        self._check(src, len(order))
        self._check(dst, len(order))
        cid = order.pop(src - 1)
        order.insert(dst - 1, cid)
        return cid

    def swap(self, engine: Engine, seat: str, a: int, b: int) -> tuple[str, str]:
        order = self._to_free(engine, seat)
        self._check(a, len(order))
        self._check(b, len(order))
        order[a - 1], order[b - 1] = order[b - 1], order[a - 1]
        return order[b - 1], order[a - 1]

    @staticmethod
    def _check(n: int, size: int) -> None:
        if not 1 <= n <= size:
            raise ValueError(f"Số thứ tự {n} không hợp lệ (1..{size}).")

    def to_meta(self) -> dict:
        return {"mode": self.mode, "custom": list(self.custom)}

    @classmethod
    def from_meta(cls, data: object, hand: list[str]) -> HandArrangement:
        arr = cls()
        if isinstance(data, dict) and data.get("mode") in MODES:
            arr.mode = data["mode"]
            custom = data.get("custom")
            if isinstance(custom, list):
                arr.custom = [i for i in custom if isinstance(i, str) and i in hand]
        return arr


__all__ = ["HandArrangement", "MODES", "MODE_VI", "MELD_VI"]
