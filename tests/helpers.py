"""Tiện ích dựng tình huống: hoán đổi quân giữa các vùng mà vẫn giữ bất biến 112 quân."""
from __future__ import annotations

from tusac.engine import Engine
from tusac.models import SEATS


def _locate(engine: Engine, cid: str) -> tuple[str, str | None]:
    s = engine.state
    for seat in SEATS:
        if cid in s.hands[seat]:
            return "hand", seat
    if cid in s.stock:
        return "stock", None
    raise AssertionError(f"{cid} không ở tay/nọc")


def _swap(engine: Engine, cid: str, seat: str, protect: set[str]) -> None:
    """Đưa `cid` vào tay `seat`, đổi lại một quân không được bảo vệ."""
    s = engine.state
    where, owner = _locate(engine, cid)
    if where == "hand" and owner == seat:
        return
    give_back = next(i for i in s.hands[seat] if i not in protect)
    s.hands[seat].remove(give_back)
    s.hands[seat].append(cid)
    if where == "hand":
        assert owner is not None
        s.hands[owner].remove(cid)
        s.hands[owner].append(give_back)
    else:
        s.stock[s.stock.index(cid)] = give_back


def rig(engine: Engine, layout: dict[str, list[str]], stock_top: list[str] | None = None, initial: bool = True) -> None:
    """Đặt các quân chỉ định vào tay từng nhà (và đầu nọc), phần còn lại giữ nguyên."""
    s = engine.state
    protect = {cid for ids in layout.values() for cid in ids} | set(stock_top or [])
    for seat, ids in layout.items():
        for cid in ids:
            _swap(engine, cid, seat, protect)
    for n, cid in enumerate(stock_top or []):
        where, owner = _locate(engine, cid)
        if where == "hand":
            assert owner is not None
            spare = next(i for i in s.stock[len(stock_top or []):] if i not in protect)
            s.hands[owner].remove(cid)
            s.hands[owner].append(spare)
            s.stock[s.stock.index(spare)] = cid
        cur = s.stock.index(cid)
        s.stock[n], s.stock[cur] = s.stock[cur], s.stock[n]
    for seat in SEATS:
        s.hands[seat].sort()
    if initial:
        s.initial_hands = {seat: list(ids) for seat, ids in s.hands.items()}
    engine.check_invariants()


def set_hand(engine: Engine, seat: str, ids: list[str]) -> None:
    """Đặt chính xác bài trên tay một nhà (đủ số lượng)."""
    assert len(ids) == len(engine.state.hands[seat])
    rig(engine, {seat: ids})
    assert sorted(engine.state.hands[seat]) == sorted(ids)


def move_to_stock(engine: Engine, ids: list[str]) -> None:
    """Đảm bảo các quân nằm trong nọc (không ở tay ai), đặt ở cuối nọc."""
    s = engine.state
    for cid in ids:
        where, owner = _locate(engine, cid)
        if where == "hand":
            assert owner is not None
            spare = next(i for i in reversed(s.stock) if i not in ids)
            s.hands[owner].remove(cid)
            s.hands[owner].append(spare)
            s.stock[s.stock.index(spare)] = cid
    s.initial_hands = {seat: list(h) for seat, h in s.hands.items()}
    engine.check_invariants()
