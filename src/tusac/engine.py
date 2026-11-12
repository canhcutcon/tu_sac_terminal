"""Máy trạng thái của ván Tứ Sắc.

SETUP → DEAL → TURN_START → DISCARD → CLAIM_WINDOW → RESOLVE_CLAIMS → (claim) DISCARD
                                                              ↘ (không ai ăn) DRAW_FROM_STOCK → EVALUATE
EVALUATE → (ăn) WIN_CHECK → DISCARD | ROUND_END ;  EVALUATE → (bỏ) CLAIM_WINDOW
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .deck import card, cards, deal, sort_ids
from .melds import analyze
from .models import (
    DECK_SIZE,
    MELD_VI,
    SEATS,
    Action,
    Claim,
    Discard,
    DiscardEvent,
    Draw,
    Event,
    GameState,
    Meld,
    MeldKind,
    Pass,
    Phase,
    RuleResult,
    action_to_dict,
    next_seat,
)
from .rules.training import TableRuleset


class InvariantError(AssertionError):
    pass


@dataclass
class Decision:
    seat: str | None
    action: str
    result: RuleResult


def meld_label(kind: MeldKind, ids: list[str]) -> str:
    cs = sorted(cards(ids))
    if kind in (MeldKind.PAIR, MeldKind.TRIPLET, MeldKind.QUAD):
        return f"{MELD_VI[kind]} {cs[0].name_vi()}"
    if kind in (MeldKind.ODD_GAE, MeldKind.ODD_CCH):
        return f"{MELD_VI[kind]} {cs[0].name_vi().split()[-1]}"
    return f"{MELD_VI[kind]} ({'/'.join(c.name_vi().split()[-1] for c in cs)})"


@dataclass
class Engine:
    rules: TableRuleset
    state: GameState
    strict: bool = True
    action_log: list[dict] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    # ------------------------------------------------------------ setup

    @classmethod
    def new_game(cls, seed: int, rules: TableRuleset, dealer: str = "A", strict: bool = True) -> Engine:
        if dealer not in SEATS:
            raise ValueError(f"Nhà cái không hợp lệ: {dealer!r}")
        state = GameState(seed=seed, ruleset_id=rules.id, dealer=dealer)
        engine = cls(rules, state, strict)
        engine._setup()
        return engine

    def _setup(self) -> None:
        s = self.state
        s.phase = Phase.DEAL
        hands, stock = deal(s.seed, s.dealer)
        s.hands = {seat: sort_ids(c.id for c in hands[seat]) for seat in SEATS}
        s.initial_hands = {seat: list(ids) for seat, ids in s.hands.items()}
        s.stock = [c.id for c in stock]
        self._event(
            s.dealer,
            "deal",
            f"Chia bài (seed {s.seed}): nhà cái {s.dealer} 21 quân, ba nhà còn lại 20 quân, nọc {len(s.stock)} quân.",
        )
        self.check_invariants()
        s.current_seat = s.dealer
        s.phase = Phase.TURN_START
        if self.rules.is_win(s, s.dealer):
            self._finish(s.dealer, f"Nhà cái {s.dealer} tới ngay khi chia bài (không còn rác).")
        else:
            s.phase = Phase.DISCARD

    # ------------------------------------------------------------ queries

    def awaiting(self) -> list[str]:
        s = self.state
        if s.phase in (Phase.DISCARD, Phase.DRAW_FROM_STOCK, Phase.EVALUATE):
            return [s.current_seat]
        if s.phase == Phase.CLAIM_WINDOW:
            return list(s.awaiting)
        return []

    @property
    def over(self) -> bool:
        return self.state.phase == Phase.ROUND_END

    def all_cards_in_zones(self) -> list[str]:
        """Gom mỗi quân đúng một lần từ mọi vùng: tay, nọc, bài bỏ, bộ mở, quân đang chờ."""
        s = self.state
        ids: list[str] = []
        for seat in SEATS:
            ids.extend(s.hands[seat])
        ids.extend(s.stock)
        ids.extend(ev.card_id for ev in s.discard_pile)
        for seat in SEATS:
            for meld in s.exposed_melds[seat]:
                ids.extend(meld.card_ids)
        if s.pending_card_id is not None:
            ids.append(s.pending_card_id)
        return ids

    def check_invariants(self) -> None:
        ids = self.all_cards_in_zones()
        if len(ids) != DECK_SIZE:
            raise InvariantError(f"Tổng số quân là {len(ids)}, phải là {DECK_SIZE}")
        if len(set(ids)) != DECK_SIZE:
            raise InvariantError("Có quân bị nhân đôi giữa các vùng")
        s = self.state
        has_pending = s.pending_card_id is not None
        if has_pending != (s.phase in (Phase.CLAIM_WINDOW, Phase.EVALUATE)):
            raise InvariantError(f"pending_card_id={s.pending_card_id} không khớp phase {s.phase}")

    # ------------------------------------------------------------ apply

    def apply(self, action: Action) -> RuleResult:
        idx = len(self.decisions)
        result = self._dispatch(action)
        # ghi quyết định của action trước các quyết định phân xử phát sinh bên trong nó
        self.decisions.insert(idx, Decision(action.seat, type(action).__name__.lower(), result))
        if result.allowed:
            self.action_log.append(action_to_dict(action))
        if self.strict:
            self.check_invariants()
        return result

    def _reject(self, code: str, message: str) -> RuleResult:
        return RuleResult(False, False, code, message)

    def _dispatch(self, action: Action) -> RuleResult:
        s = self.state
        if s.phase == Phase.ROUND_END:
            return self._reject("round_over", "Ván đã kết thúc.")
        if action.seat not in self.awaiting():
            waiting = ", ".join(self.awaiting()) or "-"
            return self._reject("not_your_turn", f"Chưa đến lượt {action.seat} hành động (đang chờ: {waiting}).")
        if isinstance(action, Discard):
            if s.phase != Phase.DISCARD:
                return self._reject("wrong_phase", "Bây giờ chưa phải lúc đánh bài.")
            return self._discard(action)
        if isinstance(action, Draw):
            if s.phase != Phase.DRAW_FROM_STOCK:
                return self._reject("wrong_phase", "Chưa được bốc nọc ở bước này.")
            return self._draw(action)
        if isinstance(action, Claim):
            if s.phase not in (Phase.CLAIM_WINDOW, Phase.EVALUATE):
                return self._reject("wrong_phase", "Không có quân nào để ăn lúc này.")
            return self._claim(action)
        if isinstance(action, Pass):
            if s.phase not in (Phase.CLAIM_WINDOW, Phase.EVALUATE):
                return self._reject("wrong_phase", "Không có gì để bỏ qua lúc này.")
            return self._pass(action)
        return self._reject("unknown_action", f"Action không hợp lệ: {action!r}")

    # ------------------------------------------------------------ transitions

    def _discard(self, a: Discard) -> RuleResult:
        s = self.state
        res = self.rules.check_discard(s, a.seat, a.card_id)
        if not res.allowed:
            return res
        s.hands[a.seat].remove(a.card_id)
        s.turn_no += 1
        s.pending_card_id, s.pending_from, s.pending_origin = a.card_id, a.seat, "discard"
        name = card(a.card_id).name_vi()
        self._event(a.seat, "discard", f"{a.seat} đánh [{name}].", [a.card_id])
        self._open_claim_window()
        return RuleResult(True, False, "discard_ok", f"{a.seat} đánh {name}.")

    def _draw(self, a: Draw) -> RuleResult:
        s = self.state
        cid = s.stock.pop(0)
        s.turn_no += 1
        s.pending_card_id, s.pending_from, s.pending_origin = cid, a.seat, "draw"
        s.phase = Phase.EVALUATE
        name = card(cid).name_vi()
        self._event(a.seat, "draw", f"{a.seat} bốc nọc: [{name}] (nọc còn {len(s.stock)}).", [cid])
        if not self.rules.legal_claims(s, a.seat):
            self._event(a.seat, "release", f"{a.seat} không ghép được [{name}] → để lại cho các nhà khác.", [cid])
            self._open_claim_window()
        return RuleResult(True, False, "draw_ok", f"{a.seat} bốc {name}.")

    def _claim(self, a: Claim) -> RuleResult:
        s = self.state
        res = self.rules.validate_claim(s, a)
        if not res.allowed:
            return res
        if s.phase == Phase.EVALUATE:
            self._apply_claim(a, "Người bốc được quyền dùng quân vừa bốc trước.")
            return res
        s.claims[a.seat] = a
        s.awaiting.remove(a.seat)
        if not s.awaiting:
            self._resolve_claims()
        return res

    def _pass(self, a: Pass) -> RuleResult:
        s = self.state
        if self.rules.mandatory_claims(s, a.seat):
            return self._reject("mandatory_claim", "Profile bắt buộc bạn phải ăn quân này (xem `hint`).")
        if s.phase == Phase.EVALUATE:
            name = card(s.pending_card_id).name_vi()  # type: ignore[arg-type]
            self._event(a.seat, "release", f"{a.seat} không dùng [{name}] → để lại cho các nhà khác.", [s.pending_card_id])  # type: ignore[list-item]
            self._open_claim_window()
            return RuleResult(True, False, "pass_ok", "Bỏ quân vừa bốc.")
        s.claims[a.seat] = None
        s.awaiting.remove(a.seat)
        if not s.awaiting:
            self._resolve_claims()
        return RuleResult(True, False, "pass_ok", "Bỏ quyền ăn.")

    def _open_claim_window(self) -> None:
        s = self.state
        assert s.pending_from is not None and s.pending_card_id is not None
        s.phase = Phase.CLAIM_WINDOW
        order = [next_seat(s.pending_from, k) for k in range(1, len(SEATS))]
        s.claims = {}
        s.awaiting = [seat for seat in order if self.rules.legal_claims(s, seat)]
        if not s.awaiting:
            self._resolve_claims()

    def _resolve_claims(self) -> None:
        s = self.state
        s.phase = Phase.RESOLVE_CLAIMS
        claims = [c for c in s.claims.values() if c is not None]
        winner, why = self.rules.resolve_priority(s, claims)
        s.claims, s.awaiting = {}, []
        self.decisions.append(Decision(winner.seat if winner else None, "resolve", RuleResult(winner is not None, False, "priority", why)))
        if winner is not None:
            self._apply_claim(winner, why)
            return
        assert s.pending_card_id is not None and s.pending_from is not None and s.pending_origin is not None
        s.discard_pile.append(DiscardEvent(s.pending_card_id, s.pending_from, s.turn_no, s.pending_origin))
        frm = s.pending_from
        s.pending_card_id = s.pending_from = s.pending_origin = None
        self._next_turn(next_seat(frm))

    def _next_turn(self, seat: str) -> None:
        s = self.state
        s.current_seat = seat
        s.phase = Phase.TURN_START
        if not s.stock:
            self._finish(None, "Hết nọc mà chưa ai tới → hòa ván (stock_empty=draw_game).")
            return
        s.phase = Phase.DRAW_FROM_STOCK

    def _apply_claim(self, claim: Claim, why: str) -> None:
        s = self.state
        cid = s.pending_card_id
        assert cid is not None
        seat = claim.seat
        for i in claim.card_ids:
            s.hands[seat].remove(i)
        initial = set(s.initial_hands[seat])
        provenance = "dealt" if all(i in initial for i in claim.card_ids) else "formed"
        meld = Meld(
            kind=claim.kind,
            card_ids=sort_ids([*claim.card_ids, cid]),
            provenance=provenance,
            claimed_card_id=cid,
            source_seat=s.pending_from,
            origin=s.pending_origin,
        )
        s.exposed_melds[seat].append(meld)
        s.pending_card_id = s.pending_from = s.pending_origin = None
        s.current_seat = seat
        note = ""
        if claim.kind in (MeldKind.TRIPLET, MeldKind.QUAD):
            note = " (khui từ bộ có sẵn khi chia)" if provenance == "dealt" else " (bộ hình thành trong ván)"
        self._event(
            seat,
            "claim",
            f"{seat} ăn [{card(cid).name_vi()}] → {meld_label(claim.kind, meld.card_ids)}{note}. {why}",
            meld.card_ids,
        )
        s.phase = Phase.WIN_CHECK
        if self.rules.is_win(s, seat):
            self._finish(seat, f"{seat} TỚI: mọi quân trên tay đều thành phe.")
        else:
            s.phase = Phase.DISCARD

    def _finish(self, winner: str | None, reason: str) -> None:
        s = self.state
        s.winner = winner
        s.end_reason = reason
        s.phase = Phase.ROUND_END
        score = self.rules.score_round(s)
        s.scores = dict(score.points)
        self._event(winner, "round_end", f"{reason} {score.summary}")

    def _event(self, seat: str | None, kind: str, text: str, ids: list[str] | None = None) -> None:
        self.state.history.append(Event(self.state.turn_no, seat, kind, text, list(ids or [])))

    # ------------------------------------------------------------ misc

    def hand_analysis(self, seat: str):
        return analyze(cards(self.state.hands[seat]), self.rules.meld_rules)
