"""Bot Easy / Medium. Chỉ đọc bài của chính mình + thông tin công khai; gọi cùng Ruleset với người chơi."""
from __future__ import annotations

import random
from collections import Counter

from .deck import card, cards
from .engine import Engine
from .melds import CCH, GAE
from .models import COPIES, MELD_VI, Action, Card, Claim, Color, Discard, Draw, GameState, Pass, Phase, Rank
from .rules.base import ClaimOption
from .rules.training import TableRuleset

LEVELS = ("easy", "medium")


def public_seen(state: GameState) -> Counter:
    """Đếm (màu, loại) đã lộ: bài bỏ, bộ mở, quân đang chờ."""
    seen: Counter = Counter()
    for ev in state.discard_pile:
        seen[card(ev.card_id).kind] += 1
    for melds in state.exposed_melds.values():
        for m in melds:
            for i in m.card_ids:
                seen[card(i).kind] += 1
    if state.pending_card_id:
        seen[card(state.pending_card_id).kind] += 1
    return seen


def partner_kinds(c: Card) -> list[tuple[Color, Rank]]:
    kinds = [c.kind]
    for trio in (GAE, CCH):
        if c.rank in trio:
            kinds += [(c.color, r) for r in trio if r != c.rank]
    if c.rank == Rank.PAWN:
        kinds += [(col, Rank.PAWN) for col in Color if col != c.color]
    return kinds


def usefulness(c: Card, hand: list[Card], seen: Counter) -> int:
    """Độ "có ích" của một quân: quân ghép được đang có trên tay + số quân ghép được chưa lộ."""
    in_hand = Counter(x.kind for x in hand)
    in_hand[c.kind] -= 1  # không tính chính nó
    score = 0
    for k in partner_kinds(c):
        held = in_hand[k]
        unseen = max(0, COPIES - seen[k] - held - (1 if k == c.kind else 0))
        score += 3 * held + unseen
    return score


def advise_discard(state: GameState, rules: TableRuleset, seat: str) -> tuple[str, str]:
    """Đánh quân làm rác còn lại ít nhất; hòa thì đánh quân ít khả năng ghép nhất."""
    hand = cards(state.hands[seat])
    seen = public_seen(state)
    best: tuple[int, int, Card] | None = None
    tried: set = set()
    for cid in rules.legal_discards(state, seat):
        c = card(cid)
        if c.kind in tried:
            continue
        tried.add(c.kind)
        rest = list(hand)
        rest.remove(c)
        key = (rules.trash(rest), usefulness(c, hand, seen), c)
        if best is None or key < best:
            best = key
    assert best is not None
    t, u, c = best
    before = rules.trash(hand)
    return c.id, f"Đánh {c.name_vi()}: rác {before}→{t}; quân này ít khả năng ghép nhất (điểm ghép {u})."


def advise_claim(options: list[ClaimOption]) -> tuple[ClaimOption | None, str]:
    allowed = [o for o in options if o.allowed]
    if not allowed:
        return None, "Không có cách ăn hợp lệ."
    for pick in (lambda o: o.wins, lambda o: o.mandatory):
        hits = [o for o in allowed if pick(o)]
        if hits:
            o = hits[0]
            tag = "để tới" if o.wins else "vì profile bắt buộc"
            return o, f"Ăn thành {MELD_VI[o.claim.kind]} {tag}."
    best = min(allowed, key=lambda o: (o.trash_after, -len(o.claim.card_ids)))
    if best.trash_after < best.trash_before:
        gain = best.trash_before - best.trash_after
        return best, f"Ăn vì hoàn thành {MELD_VI[best.claim.kind]}; giảm {gain} quân rác ({best.trash_before}→{best.trash_after})."
    return None, f"Không ăn: không bộ nào giảm được rác (đang {best.trash_before} rác)."


class Bot:
    def __init__(self, level: str = "medium"):
        if level not in LEVELS:
            raise ValueError(f"Mức bot không hợp lệ: {level!r} (chọn {', '.join(LEVELS)})")
        self.level = level

    def rng(self, engine: Engine, seat: str) -> random.Random:
        # Xác định hoàn toàn từ seed + số action đã chơi → replay ra cùng kết quả.
        return random.Random(f"{engine.state.seed}:{len(engine.action_log)}:{seat}:{self.level}")

    def decide(self, engine: Engine, seat: str) -> tuple[Action, str]:
        s = engine.state
        rules = engine.rules
        rng = self.rng(engine, seat)
        if s.phase == Phase.DRAW_FROM_STOCK:
            return Draw(seat), "Không ai ăn quân trước → bốc nọc."
        if s.phase == Phase.DISCARD:
            if self.level == "easy":
                analysis = engine.hand_analysis(seat)
                legal = set(rules.legal_discards(s, seat))
                pool = [c.id for c in analysis.trash if c.id in legal] or sorted(legal)
                cid = rng.choice(pool)
                return Discard(seat, cid), f"Đánh ngẫu nhiên một quân rác: {card(cid).name_vi()}."
            cid, why = advise_discard(s, rules, seat)
            return Discard(seat, cid), why
        if s.phase in (Phase.CLAIM_WINDOW, Phase.EVALUATE):
            options = rules.evaluate_claims(s, seat)
            if self.level == "easy":
                allowed = [o for o in options if o.allowed]
                forced = [o for o in allowed if o.wins] or [o for o in allowed if o.mandatory]
                if forced:
                    o = forced[0]
                    return o.claim, f"Ăn thành {MELD_VI[o.claim.kind]} ({'tới' if o.wins else 'bắt buộc'})."
                if allowed and rng.random() < 0.6:
                    o = rng.choice(allowed)
                    return o.claim, f"Ăn ngẫu nhiên thành {MELD_VI[o.claim.kind]}."
                return Pass(seat), "Bỏ qua."
            choice, why = advise_claim(options)
            if choice is not None:
                return choice.claim, why
            return Pass(seat), why
        raise RuntimeError(f"Bot {seat} không có gì để làm ở phase {s.phase}")


def is_claim(action: Action) -> bool:
    return isinstance(action, Claim)
