"""Nhận diện bộ (phe) và phân tích rác — các hàm thuần, không phụ thuộc trạng thái ván."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations

from .models import Card, Color, MeldKind, Rank

GAE = (Rank.GENERAL, Rank.ADVISOR, Rank.ELEPHANT)
CCH = (Rank.CHARIOT, Rank.CANNON, Rank.HORSE)
N_RANKS = len(Rank)
N_CELLS = len(Color) * N_RANKS

SINGLE_GENERAL = "single_general"
TRASH = "trash"


@dataclass(frozen=True)
class MeldRules:
    pawn_trio: bool = True
    pawn_quad: bool = True
    lone_general_ok: bool = True  # Tướng đứng một mình không tính là rác
    pairs_ok: bool = True  # đôi được tính là phe khi xét rác/tới


DEFAULT_MELD_RULES = MeldRules()


def identify_meld(cards: Sequence[Card], rules: MeldRules = DEFAULT_MELD_RULES) -> MeldKind | None:
    """Trả về loại bộ nếu `cards` (2–4 quân) tạo thành một bộ hợp lệ, ngược lại None."""
    n = len(cards)
    if n < 2 or n > 4 or len({c.id for c in cards}) != n:
        return None
    kinds = {c.kind for c in cards}
    colors = {c.color for c in cards}
    ranks = {c.rank for c in cards}
    if len(kinds) == 1:
        return {2: MeldKind.PAIR, 3: MeldKind.TRIPLET, 4: MeldKind.QUAD}[n]
    if n == 3 and len(colors) == 1:
        if ranks == set(GAE):
            return MeldKind.ODD_GAE
        if ranks == set(CCH):
            return MeldKind.ODD_CCH
    if ranks == {Rank.PAWN} and len(colors) == n:
        if n == 3 and rules.pawn_trio:
            return MeldKind.PAWN_TRIO
        if n == 4 and rules.pawn_quad:
            return MeldKind.PAWN_QUAD
    return None


def meld_options_with(
    hand: Sequence[Card], new: Card, rules: MeldRules = DEFAULT_MELD_RULES
) -> list[tuple[MeldKind, tuple[Card, ...]]]:
    """Mọi cách ghép quân `new` với quân trên tay thành một bộ ("có thể tạo bộ")."""
    by_kind: dict[tuple[Color, Rank], list[Card]] = defaultdict(list)
    for c in sorted(hand):
        by_kind[c.kind].append(c)
    out: list[tuple[MeldKind, tuple[Card, ...]]] = []
    same = by_kind.get(new.kind, [])
    for size, kind in ((1, MeldKind.PAIR), (2, MeldKind.TRIPLET), (3, MeldKind.QUAD)):
        if len(same) >= size:
            out.append((kind, tuple(same[:size])))
    for trio, kind in ((GAE, MeldKind.ODD_GAE), (CCH, MeldKind.ODD_CCH)):
        if new.rank in trio:
            picks = [by_kind.get((new.color, r)) for r in trio if r != new.rank]
            if all(picks):
                out.append((kind, tuple(p[0] for p in picks)))  # type: ignore[index]
    if new.rank == Rank.PAWN:
        others = [c for c in Color if c != new.color and by_kind.get((c, Rank.PAWN))]
        if rules.pawn_trio:
            for combo in combinations(others, 2):
                out.append((MeldKind.PAWN_TRIO, tuple(by_kind[(c, Rank.PAWN)][0] for c in combo)))
        if rules.pawn_quad and len(others) == 3:
            out.append((MeldKind.PAWN_QUAD, tuple(by_kind[(c, Rank.PAWN)][0] for c in others)))
    return out


# ------------------------------------------------------------ Phân tích rác


def _counts(cards: Sequence[Card]) -> tuple[int, ...]:
    counts = [0] * N_CELLS
    for c in cards:
        counts[c.cell] += 1
    return tuple(counts)


Plan = tuple[tuple[str, tuple[int, ...]], ...]


@lru_cache(maxsize=500_000)
def _solve(counts: tuple[int, ...], rules: MeldRules) -> tuple[int, Plan]:
    """Chia tay bài thành các phe sao cho số quân rác ít nhất.

    Luôn xử lý ô khác 0 đầu tiên: mọi bộ chứa ô đó đều có ô đó là phần tử nhỏ nhất,
    nên duyệt các lựa chọn cho ô này là đầy đủ.
    """
    i = next((k for k, v in enumerate(counts) if v), -1)
    if i < 0:
        return 0, ()
    color, rank = divmod(i, N_RANKS)
    n = counts[i]
    best: tuple[int, Plan] | None = None

    def consider(cost: int, cells: tuple[int, ...], label: str) -> None:
        nonlocal best
        nxt = list(counts)
        for cell in cells:
            nxt[cell] -= 1
        sub_cost, sub_plan = _solve(tuple(nxt), rules)
        total = cost + sub_cost
        if best is None or total < best[0]:
            best = (total, ((label, cells),) + sub_plan)

    if n >= 4:
        consider(0, (i,) * 4, MeldKind.QUAD.value)
    if n >= 3:
        consider(0, (i,) * 3, MeldKind.TRIPLET.value)
    if rank == Rank.GENERAL and counts[i + 1] and counts[i + 2]:
        consider(0, (i, i + 1, i + 2), MeldKind.ODD_GAE.value)
    if rank == Rank.CHARIOT and counts[i + 1] and counts[i + 2]:
        consider(0, (i, i + 1, i + 2), MeldKind.ODD_CCH.value)
    if rank == Rank.PAWN:
        higher = [k * N_RANKS + Rank.PAWN for k in range(color + 1, len(Color)) if counts[k * N_RANKS + Rank.PAWN]]
        if rules.pawn_quad and len(higher) == 3:
            consider(0, (i, *higher), MeldKind.PAWN_QUAD.value)
        if rules.pawn_trio:
            for combo in combinations(higher, 2):
                consider(0, (i, *combo), MeldKind.PAWN_TRIO.value)
    if n >= 2 and rules.pairs_ok:
        consider(0, (i, i), MeldKind.PAIR.value)
    if rank == Rank.GENERAL and rules.lone_general_ok:
        consider(0, (i,), SINGLE_GENERAL)
    else:
        consider(1, (i,), TRASH)
    assert best is not None
    return best


@dataclass(frozen=True)
class HandAnalysis:
    trash: list[Card]
    groups: list[tuple[str, list[Card]]]  # (nhãn bộ, quân) — nhãn là MeldKind.value hoặc single_general

    @property
    def trash_count(self) -> int:
        return len(self.trash)


def trash_count(cards: Sequence[Card], rules: MeldRules = DEFAULT_MELD_RULES) -> int:
    return _solve(_counts(cards), rules)[0]


def analyze(cards: Sequence[Card], rules: MeldRules = DEFAULT_MELD_RULES) -> HandAnalysis:
    _, plan = _solve(_counts(cards), rules)
    pool: dict[int, list[Card]] = defaultdict(list)
    for c in sorted(cards):
        pool[c.cell].append(c)
    trash: list[Card] = []
    groups: list[tuple[str, list[Card]]] = []
    for label, cells in plan:
        picked = [pool[cell].pop(0) for cell in cells]
        if label == TRASH:
            trash.extend(picked)
        else:
            groups.append((label, picked))
    return HandAnalysis(trash=trash, groups=groups)
