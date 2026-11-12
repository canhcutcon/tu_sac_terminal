"""Vẽ bàn chơi bằng Rich. Luôn in tên màu — không dùng màu chữ làm tín hiệu duy nhất."""
from __future__ import annotations

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from .deck import card
from .engine import Engine, meld_label
from .models import COLOR_VI, PHASE_VI, RANK_HAN, SEATS, Card, Color, Phase

COLOR_STYLE = {
    Color.RED: "bold red",
    Color.GREEN: "bold green",
    Color.YELLOW: "bold yellow",
    Color.WHITE: "bold bright_white",
}


def card_label(c: Card, ascii_only: bool) -> str:
    return c.name_vi() if ascii_only else f"{c.name_vi()} {RANK_HAN[c.rank]}"


def card_text(c: Card, ascii_only: bool, index: int | None = None, names: bool = True) -> Text:
    """names=False: chỉ in chữ Hán tô màu. Chế độ ASCII luôn in tên (không có chữ Hán)."""
    t = Text()
    if index is not None:
        t.append(f"[{index:02d}]", style="cyan")
        t.append(" ")
    label = card_label(c, ascii_only) if names or ascii_only else RANK_HAN[c.rank]
    t.append(label, style=COLOR_STYLE[c.color])
    return t


def _rule(ascii_only: bool) -> Rule:
    return Rule(characters="-" if ascii_only else "─", style="dim")


def render_hand_rows(
    rows: list[tuple[str, str, list[str], str]], order: list[str], ascii_only: bool, width: int = 100,
    names: bool = True,
) -> RenderableType:
    """Vẽ các hàng (nhãn, style, ids, ghi chú); số thứ tự theo `order`; xuống dòng theo nguyên quân."""
    index = {cid: n for n, cid in enumerate(order, 1)}
    label_w = max((len(label) for label, _, ids, note in rows if ids or note), default=4)
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True)
    grid.add_column(no_wrap=True)
    avail = max(24, width - label_w - 2)
    for label, style, ids, note in rows:
        if not ids and not note:
            continue
        row = Text()
        line_len = 0
        for cid in ids:
            piece = card_text(card(cid), ascii_only, index[cid], names)
            if line_len and line_len + piece.cell_len > avail:
                row.append("\n")
                line_len = 0
            row.append_text(piece)
            row.append("  ")
            line_len += piece.cell_len + 2
        if note:
            row.append(f"  {note}" if ids else note, style="dim italic")
        grid.add_row(Text(label.ljust(label_w), style=style), row)
    return grid


def render_melds(engine: Engine, ascii_only: bool) -> RenderableType:
    s = engine.state
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True)
    grid.add_column()
    for seat in SEATS:
        melds = s.exposed_melds[seat]
        t = Text()
        if not melds:
            t.append("—", style="dim")
        for m in melds:
            first = card(m.card_ids[0])
            t.append("[", style="dim")
            t.append(meld_label(m.kind, m.card_ids), style=COLOR_STYLE[first.color] if m.kind.value not in ("pawn_trio", "pawn_quad") else "bold magenta")
            t.append("] ", style="dim")
        grid.add_row(Text(f"{seat}[{len(melds)}]", style="bold"), t)
    return grid


def render_table(
    engine: Engine,
    me: str | None,
    *,
    ascii_only: bool,
    round_no: int,
    tally: dict[str, int],
    prompt: Text | None = None,
    hand_view: RenderableType | None = None,
    hand_title: str = "",
    names: bool = True,
) -> Panel:
    s = engine.state
    parts: list[RenderableType] = []
    head = Text()
    if me:
        head.append(f"Bạn: {me}", style="bold cyan")
        head.append("  |  ")
    head.append(f"Lượt: {s.current_seat} ({PHASE_VI[s.phase]})")
    head.append(f"  |  Nọc: {len(s.stock)}  |  Luật: {s.ruleset_id}  |  Seed: {s.seed}")
    parts.append(head)
    counts = Text()
    for seat in SEATS:
        tag = " (cái)" if seat == s.dealer else ""
        style = "bold cyan" if seat == me else ""
        counts.append(f"{seat}{tag}: {len(s.hands[seat])} lá", style=style)
        counts.append(f" [{tally.get(seat, 0)} thắng]   ", style="dim")
    parts.append(counts)
    parts.append(_rule(ascii_only))

    cur = Text("Quân mới: ")
    if s.pending_card_id:
        cur.append_text(card_text(card(s.pending_card_id), ascii_only, names=names))
        origin = "bốc nọc" if s.pending_origin == "draw" else "đánh ra"
        cur.append(f" từ {s.pending_from} ({origin})")
        if s.phase == Phase.CLAIM_WINDOW:
            cur.append("  |  Đang chờ quyền ăn", style="yellow")
    elif s.discard_pile:
        last = s.discard_pile[-1]
        cur.append("— ", style="dim")
        cur.append("(quân vừa bỏ: ", style="dim")
        cur.append_text(card_text(card(last.card_id), ascii_only, names=names))
        cur.append(f" của {last.seat})", style="dim")
    else:
        cur.append("—", style="dim")
    parts.append(cur)

    recent = Text("Bài đã bỏ: ", style="dim")
    for ev in s.discard_pile[-8:]:
        recent.append_text(card_text(card(ev.card_id), ascii_only, names=names))
        recent.append(f"({ev.seat}) ", style="dim")
    if not s.discard_pile:
        recent.append("—")
    parts.append(recent)
    parts.append(Text("Bộ mở:", style="bold"))
    parts.append(render_melds(engine, ascii_only))

    if me:
        parts.append(_rule(ascii_only))
        parts.append(Text(f"BÀI CỦA BẠN ({len(s.hands[me])} lá){hand_title}", style="bold"))
        if hand_view is not None:
            parts.append(hand_view)
    if prompt is not None:
        parts.append(_rule(ascii_only))
        parts.append(prompt)
    return Panel(
        Group(*parts),
        title=f"TỨ SẮC / VÁN #{round_no}",
        box=box.ASCII if ascii_only else box.ROUNDED,
        border_style="cyan",
    )
