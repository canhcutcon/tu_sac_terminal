"""Xếp bài trên tay người chơi: theo màu / theo loại / khu vực xếp bộ / tự do (move, swap).

Chỉ ảnh hưởng cách hiển thị và số thứ tự quân — không đụng tới trạng thái ván.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .deck import card, cards, sort_ids
from .engine import Engine
from .melds import MeldRules, analyze, identify_meld, trash_count
from .models import COLOR_VI, MELD_VI, RANK_VI, Color, MeldKind, Rank
from .trainer import group_label

MODES = ("color", "rank", "meld", "free")
MODE_VI = {
    "color": "theo màu",
    "rank": "theo loại quân",
    "meld": "khu vực xếp bộ",
    "free": "tự do",
}
_COLOR_STYLE = {Color.RED: "bold red", Color.GREEN: "bold green", Color.YELLOW: "bold yellow", Color.WHITE: "bold bright_white"}
WAITING_LABEL = "Rác / chờ"

Row = tuple[str, str, list[str], str]  # (nhãn, style, ids, ghi chú sau quân)


def group_kind(ids: list[str], rules: MeldRules) -> str | None:
    """Tên bộ nếu nhóm hợp lệ (kể cả Tướng lẻ), ngược lại None."""
    cs = cards(ids)
    if len(cs) == 1:
        return "Tướng lẻ" if cs[0].rank == Rank.GENERAL and rules.lone_general_ok else None
    kind = identify_meld(cs, rules)
    if kind is None or (kind == MeldKind.PAIR and not rules.pairs_ok):
        return None
    return MELD_VI[kind]


@dataclass
class CheckReport:
    lines: list[tuple[str, bool]]  # (dòng, hợp lệ?)
    valid_groups: int
    loose: int  # quân chưa vào bộ hợp lệ
    optimal_trash: int


@dataclass
class HandArrangement:
    mode: str = "color"
    custom: list[str] = field(default_factory=list)
    groups: list[list[str]] = field(default_factory=list)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"Kiểu xếp không hợp lệ: {mode!r} (chọn {', '.join(MODES[:3])})")
        self.mode = mode

    # ------------------------------------------------------------ đồng bộ với tay bài

    def _sync(self, hand: list[str]) -> list[str]:
        """Giữ thứ tự tự xếp; bỏ quân đã rời tay, thêm quân mới vào cuối."""
        present = set(hand)
        keep = [i for i in self.custom if i in present]
        kept = set(keep)
        self.custom = keep + sort_ids(i for i in hand if i not in kept)
        return self.custom

    def _sync_groups(self, hand: list[str]) -> list[str]:
        """Bỏ quân đã rời tay khỏi các bộ, xóa bộ rỗng; trả về quân chưa xếp (Rác / chờ)."""
        present = set(hand)
        self.groups = [g2 for g in self.groups if (g2 := [i for i in g if i in present])]
        grouped = {i for g in self.groups for i in g}
        return sort_ids(i for i in hand if i not in grouped)

    # ------------------------------------------------------------ hiển thị

    def rows(self, engine: Engine, seat: str) -> list[Row]:
        hand = list(engine.state.hands[seat])
        if self.mode == "color":
            ordered = sort_ids(hand)
            return [
                (COLOR_VI[c].upper(), _COLOR_STYLE[c], [i for i in ordered if card(i).color == c], "")
                for c in Color
            ]
        if self.mode == "rank":
            ordered = sorted(hand, key=lambda i: (card(i).rank, card(i).color, card(i).copy_index))
            return [(RANK_VI[r].upper(), "bold", [i for i in ordered if card(i).rank == r], "") for r in Rank]
        if self.mode == "meld":
            loose = self._sync_groups(hand)
            rules = engine.rules.meld_rules
            rows: list[Row] = []
            for n, g in enumerate(self.groups, 1):
                kind = group_kind(g, rules)
                if kind:
                    rows.append((f"Bộ {n} ✓", "bold green", g, kind))
                else:
                    rows.append((f"Bộ {n} ✗", "bold red", g, "không phải bộ hợp lệ"))
            rows.append((WAITING_LABEL, "bold yellow", loose, "" if loose else "(trống)"))
            return rows
        return [("TAY", "bold", list(self._sync(hand)), "")]

    def title(self, engine: Engine, seat: str) -> str:
        if self.mode != "meld":
            return f" — xếp {MODE_VI[self.mode]}"
        self._sync_groups(engine.state.hands[seat])
        valid = sum(1 for g in self.groups if group_kind(g, engine.rules.meld_rules))
        return f" — KHU VỰC XẾP BỘ: {valid} bộ hợp lệ"

    def order(self, engine: Engine, seat: str) -> list[str]:
        return [cid for _, _, ids, _ in self.rows(engine, seat) for cid in ids]

    # ------------------------------------------------------------ thao tác

    def auto_groups(self, engine: Engine, seat: str) -> None:
        """Tự xếp bộ tối ưu (ít rác nhất)."""
        a = analyze(cards(engine.state.hands[seat]), engine.rules.meld_rules)
        self.groups = [[c.id for c in cs] for _, cs in a.groups]
        self.mode = "meld"

    def make_group(self, engine: Engine, seat: str, positions: list[int]) -> list[str]:
        order = self.order(engine, seat)
        if not 1 <= len(positions) <= 4 or len(set(positions)) != len(positions):
            raise ValueError("Một bộ gồm 1–4 quân khác nhau.")
        for p in positions:
            self._check(p, len(order))
        ids = [order[p - 1] for p in positions]
        if self.mode != "meld":
            self.groups = []
            self.mode = "meld"
        self.groups = [[i for i in g if i not in ids] for g in self.groups]
        self.groups = [g for g in self.groups if g]
        self.groups.append(ids)
        return ids

    def split_group(self, engine: Engine, seat: str, which: str) -> int:
        self._sync_groups(engine.state.hands[seat])
        if which == "all":
            n = len(self.groups)
            self.groups = []
            return n
        if not which.isdigit() or not 1 <= int(which) <= len(self.groups):
            raise ValueError(f"Không có bộ {which} (đang có {len(self.groups)} bộ).")
        self.groups.pop(int(which) - 1)
        return 1

    def check(self, engine: Engine, seat: str) -> CheckReport:
        hand = engine.state.hands[seat]
        loose = self._sync_groups(hand)
        rules = engine.rules.meld_rules
        lines: list[tuple[str, bool]] = []
        valid = 0
        bad_cards = len(loose)
        for n, g in enumerate(self.groups, 1):
            kind = group_kind(g, rules)
            names = " + ".join(card(i).name_vi() for i in g)
            if kind:
                valid += 1
                lines.append((f"Bộ {n}: {names} → {kind}", True))
            else:
                bad_cards += len(g)
                lines.append((f"Bộ {n}: {names} → không phải bộ hợp lệ", False))
        return CheckReport(lines, valid, bad_cards, trash_count(cards(hand), rules))

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

    # ------------------------------------------------------------ lưu

    def to_meta(self) -> dict:
        return {"mode": self.mode, "custom": list(self.custom), "groups": [list(g) for g in self.groups]}

    @classmethod
    def from_meta(cls, data: object, hand: list[str]) -> HandArrangement:
        arr = cls()
        if isinstance(data, dict) and data.get("mode") in MODES:
            arr.mode = data["mode"]
            present = set(hand)
            custom = data.get("custom")
            if isinstance(custom, list):
                arr.custom = [i for i in custom if isinstance(i, str) and i in present]
            groups = data.get("groups")
            if isinstance(groups, list):
                seen: set[str] = set()
                for g in groups[:30]:
                    if isinstance(g, list):
                        ids = [i for i in g[:4] if isinstance(i, str) and i in present and i not in seen]
                        seen.update(ids)
                        if ids:
                            arr.groups.append(ids)
        return arr


__all__ = ["HandArrangement", "MODES", "MODE_VI", "group_kind", "group_label"]
