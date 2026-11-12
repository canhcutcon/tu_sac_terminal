"""Ruleset cấu hình được. Profile training_basic là luật luyện tập tối thiểu, minh bạch."""
from __future__ import annotations

from collections import Counter

from ..deck import card, cards
from ..melds import analyze, identify_meld, meld_options_with, trash_count
from ..models import (
    MELD_VI,
    SEATS,
    Card,
    Claim,
    GameState,
    MeldKind,
    Phase,
    RuleResult,
    next_seat,
    seat_distance,
)
from .base import OPTION_HELP, ClaimOption, RuleConfig, ScoreResult

KIND_PRIORITY = {MeldKind.QUAD: 0, MeldKind.TRIPLET: 1}


class TableRuleset:
    """Mọi quyết định ăn / ưu tiên / thắng / đánh đều đi qua đây và có reason_code."""

    def __init__(self, config: RuleConfig | None = None):
        self.config = config or RuleConfig()
        self.meld_rules = self.config.meld_rules()

    @property
    def id(self) -> str:
        return self.config.ruleset

    # ------------------------------------------------------------ helpers

    def hand(self, state: GameState, seat: str) -> list[Card]:
        return cards(state.hands[seat])

    def trash(self, hand: list[Card]) -> int:
        return trash_count(hand, self.meld_rules)

    def claim_role(self, state: GameState, seat: str) -> str | None:
        """self_draw: người vừa bốc; next: nhà kế tiếp người đánh; other: nhà khác; None: không có quyền."""
        if state.pending_card_id is None or state.pending_from is None:
            return None
        if state.phase == Phase.EVALUATE:
            return "self_draw" if seat == state.current_seat else None
        if state.phase in (Phase.CLAIM_WINDOW, Phase.RESOLVE_CLAIMS):
            if seat == state.pending_from:
                return None
            return "next" if seat == next_seat(state.pending_from) else "other"
        return None

    def judge_claim(self, state: GameState, seat: str, kind: MeldKind, used: list[Card]) -> ClaimOption:
        cfg = self.config
        hand = self.hand(state, seat)
        trash_before = self.trash(hand)
        rest = list(hand)
        for c in used:
            rest.remove(c)
        rest_trash = self.trash(rest)
        wins = rest_trash == 0
        trash_after = 0 if wins else rest_trash - 1
        claim = Claim(seat, tuple(c.id for c in used), kind)
        role = self.claim_role(state, seat)
        name = MELD_VI[kind]
        warning = ""
        if role is None:
            allowed, code, msg = False, "not_eligible", "Không có quyền ăn quân này ở thời điểm hiện tại."
        elif wins and (cfg.win_any_seat or role in ("self_draw", "next")):
            allowed, code, msg = True, "win_claim", f"Ăn thành {name} và tới (tay bài không còn rác)."
        elif role in ("self_draw", "next") and kind.value in cfg.claim_next_seat_kinds:
            who = "Quân tự bốc" if role == "self_draw" else "Nhà kế tiếp"
            allowed, code, msg = True, f"{role}_claim", f"{who} được dùng để ghép {name}."
        elif role == "other" and kind.value in cfg.claim_any_seat_kinds:
            allowed, code, msg = True, "any_seat_claim", f"Nhà bất kỳ được ăn ngoài lượt để thành {name}."
        else:
            allowed, code = False, "kind_not_allowed_for_seat"
            msg = f"{name} chỉ được ăn bởi nhà kế tiếp người đánh hoặc người vừa bốc."
        if allowed and not wins and trash_after > trash_before and cfg.no_increase_trash != "off":
            text = f"ăn bộ này làm rác tăng {trash_before}→{trash_after}."
            if cfg.no_increase_trash == "enforce":
                allowed, code, msg = False, "increase_trash", f"Luật cấm ăn làm tăng rác: {text}"
            else:
                warning = text
        mandatory = allowed and (
            (kind == MeldKind.TRIPLET and cfg.mandatory_pair_claim)
            or (kind == MeldKind.QUAD and cfg.khap_exposure == "auto")
        )
        if mandatory:
            msg += " (Bắt buộc ăn theo profile.)"
        return ClaimOption(claim, True, allowed, mandatory, wins, trash_before, trash_after, code, msg, warning)

    # ------------------------------------------------------------ claims

    def evaluate_claims(self, state: GameState, seat: str, card_id: str | None = None) -> list[ClaimOption]:
        card_id = card_id or state.pending_card_id
        if card_id is None:
            return []
        pending = card(card_id)
        hand = self.hand(state, seat)
        return [
            self.judge_claim(state, seat, kind, list(used))
            for kind, used in meld_options_with(hand, pending, self.meld_rules)
        ]

    def legal_claims(self, state: GameState, seat: str, card_id: str | None = None) -> list[Claim]:
        return [o.claim for o in self.evaluate_claims(state, seat, card_id) if o.allowed]

    def mandatory_claims(self, state: GameState, seat: str, card_id: str | None = None) -> list[Claim]:
        return [o.claim for o in self.evaluate_claims(state, seat, card_id) if o.mandatory]

    def validate_claim(self, state: GameState, claim: Claim) -> RuleResult:
        if state.pending_card_id is None:
            return RuleResult(False, False, "no_pending", "Không có quân nào đang chờ ăn.")
        ids = list(claim.card_ids)
        if not ids or len(set(ids)) != len(ids):
            return RuleResult(False, False, "bad_cards", "Phải chọn 1–3 quân khác nhau trên tay.")
        hand_ids = set(state.hands[claim.seat])
        if any(i not in hand_ids for i in ids):
            return RuleResult(False, False, "card_not_in_hand", "Có quân không nằm trên tay bạn.")
        used = cards(ids)
        pending = card(state.pending_card_id)
        kind = identify_meld(used + [pending], self.meld_rules)
        if kind is None:
            names = " + ".join(c.name_vi() for c in used + [pending])
            return RuleResult(False, False, "not_a_meld", f"{names} không tạo thành bộ hợp lệ.")
        if kind != claim.kind:
            return RuleResult(False, False, "kind_mismatch", f"Các quân này tạo thành {MELD_VI[kind]}, không phải {MELD_VI[claim.kind]}.")
        return self.judge_claim(state, claim.seat, kind, used).as_result()

    def resolve_priority(self, state: GameState, claims: list[Claim]) -> tuple[Claim | None, str]:
        judged = []
        for c in claims:
            opt = self.judge_claim(state, c.seat, c.kind, cards(c.card_ids))
            if opt.allowed:
                judged.append((opt, c))
        if not judged:
            return None, "Không ai ăn."
        assert state.pending_from is not None
        frm = state.pending_from

        def key(item: tuple[ClaimOption, Claim]) -> tuple[int, int, int]:
            opt, c = item
            return (0 if opt.wins else 1, KIND_PRIORITY.get(c.kind, 2), seat_distance(frm, c.seat))

        judged.sort(key=key)
        best_opt, best = judged[0]
        if len(judged) == 1:
            return best, f"Chỉ có {best.seat} đề nghị ăn."
        rivals = ", ".join(f"{c.seat} ({MELD_VI[c.kind]}{', tới' if o.wins else ''})" for o, c in judged[1:])
        if best_opt.wins:
            why = "ăn để tới được ưu tiên cao nhất"
        elif key(judged[0])[1] < key(judged[1])[1]:
            why = "Quàn > Khạp > bộ khác"
        else:
            why = "cùng hạng nên nhà gần người đánh hơn (theo chiều chơi) được ưu tiên"
        return best, f"Ưu tiên {best.seat} hơn {rivals}: {why}."

    def claim_priority(self, state: GameState, claims: list[Claim]) -> Claim | None:
        return self.resolve_priority(state, claims)[0]

    # ------------------------------------------------------------ discard / win

    def locked_kinds(self, state: GameState, seat: str) -> set[tuple]:
        if not self.config.forbid_split_khap:
            return set()
        counts = Counter(c.kind for c in self.hand(state, seat))
        return {k for k, n in counts.items() if n >= 3}

    def legal_discards(self, state: GameState, seat: str) -> list[str]:
        ids = list(state.hands[seat])
        locked = self.locked_kinds(state, seat)
        legal = [i for i in ids if card(i).kind not in locked]
        return legal or ids  # nếu mọi quân đều thuộc khạp thì không thể cấm hết

    def check_discard(self, state: GameState, seat: str, card_id: str) -> RuleResult:
        if card_id not in state.hands[seat]:
            return RuleResult(False, False, "card_not_in_hand", "Quân này không có trên tay.")
        if card_id not in self.legal_discards(state, seat):
            return RuleResult(False, False, "khap_locked", f"Profile cấm tách khạp/quàn: không được đánh {card(card_id).name_vi()}.")
        return RuleResult(True, False, "discard_ok", "Đánh quân hợp lệ.")

    def is_win(self, state: GameState, seat: str) -> bool:
        return self.trash(self.hand(state, seat)) == 0

    def score_round(self, state: GameState) -> ScoreResult:
        points = {s: 0 for s in SEATS}
        if state.winner:
            points[state.winner] = 1
            return ScoreResult(points, f"{state.winner} tới: +1 ván thắng (penalty_mode=disabled, không tính đền).")
        return ScoreResult(points, "Hòa ván, không ai được điểm.")

    def winning_hand(self, state: GameState, seat: str):
        return analyze(self.hand(state, seat), self.meld_rules)

    def describe(self) -> list[tuple[str, str, str]]:
        rows = []
        for key, value in self.config.to_dict().items():
            shown = ", ".join(value) if isinstance(value, list) else str(value).lower() if isinstance(value, bool) else str(value)
            rows.append((key, shown, OPTION_HELP.get(key, "")))
        return rows
