"""Chế độ học: hint (gợi ý + giải thích, không tự chơi) và why (giải thích quyết định luật)."""
from __future__ import annotations

from collections.abc import Callable

from .bots import advise_claim, advise_discard
from .deck import card
from .engine import Engine
from .melds import SINGLE_GENERAL
from .models import MELD_VI, MeldKind, Phase

Label = Callable[[str], str]


def group_label(label: str) -> str:
    if label == SINGLE_GENERAL:
        return "Tướng lẻ"
    return MELD_VI[MeldKind(label)]


def hint(engine: Engine, seat: str, label: Label, index_of: Callable[[str], int]) -> list[str]:
    s = engine.state
    if s.phase == Phase.ROUND_END:
        return ["Ván đã kết thúc. Gõ `new` để chơi ván mới."]
    lines: list[str] = []
    analysis = engine.hand_analysis(seat)
    trash = ", ".join(label(c.id) for c in analysis.trash) or "không có"
    lines.append(f"Tay bài {len(s.hands[seat])} quân — {analysis.trash_count} quân rác: {trash}")
    groups = "; ".join(f"{group_label(g)}: {' + '.join(c.name_vi() for c in cs)}" for g, cs in analysis.groups)
    if groups:
        lines.append(f"Phe đang có: {groups}")
    if seat not in engine.awaiting():
        lines.append(f"Chưa tới lượt bạn (đang chờ: {', '.join(engine.awaiting())}).")
        return lines
    if s.phase == Phase.DISCARD:
        cid, why = advise_discard(s, engine.rules, seat)
        lines.append(f"Gợi ý: discard {index_of(cid)} ({card(cid).name_vi()}) — {why}")
        locked = engine.rules.locked_kinds(s, seat)
        if locked:
            lines.append("Lưu ý: profile cấm tách khạp, các quân thuộc khạp/quàn không được đánh.")
    elif s.phase == Phase.DRAW_FROM_STOCK:
        lines.append("Không ai ăn quân vừa ra. Gõ `draw` để bốc nọc.")
    elif s.phase in (Phase.CLAIM_WINDOW, Phase.EVALUATE):
        pending = card(s.pending_card_id)  # type: ignore[arg-type]
        options = engine.rules.evaluate_claims(s, seat)
        lines.append(f"Quân đang xét: {pending.name_vi()} — có {len(options)} cách tạo bộ:")
        for o in options:
            flags = []
            flags.append("ĐƯỢC ĂN" if o.allowed else "KHÔNG ĐƯỢC ĂN")
            if o.mandatory:
                flags.append("BẮT BUỘC")
            if o.wins:
                flags.append("TỚI")
            used = " + ".join(label(i) for i in o.claim.card_ids)
            lines.append(
                f"  • {MELD_VI[o.claim.kind]}: {used} + {pending.name_vi()} | rác {o.trash_before}→{o.trash_after} "
                f"| {' / '.join(flags)} — {o.message}{(' ⚠ ' + o.warning) if o.warning else ''}"
            )
        choice, why = advise_claim(options)
        if choice is None:
            lines.append(f"Gợi ý: pass — {why}")
        else:
            idx = " ".join(str(index_of(i)) for i in choice.claim.card_ids)
            lines.append(f"Gợi ý: claim {idx} — {why}")
    return lines


def why(engine: Engine, n: int = 4) -> list[str]:
    if not engine.decisions:
        return ["Chưa có quyết định luật nào."]
    out = []
    for d in engine.decisions[-n:]:
        r = d.result
        verdict = "CHẤP NHẬN" if r.allowed else "TỪ CHỐI"
        if d.action == "resolve":
            verdict = "PHÂN XỬ"
        who = d.seat or "-"
        out.append(f"[{verdict}] {who} {d.action}: {r.message} (mã: {r.reason_code}{', bắt buộc' if r.mandatory else ''})")
    return out
