import pytest
from helpers import move_to_stock, rig, set_hand

from tusac.bots import Bot
from tusac.engine import Engine
from tusac.models import SEATS, Claim, Discard, Draw, MeldKind, Pass, Phase
from tusac.rules import load_ruleset
from tusac.rules.base import RuleConfig
from tusac.rules.training import TableRuleset

XE = ["RED-CHARIOT-0", "RED-CHARIOT-1", "RED-CHARIOT-2", "RED-CHARIOT-3"]


def new(seed=3, config=None, dealer="A"):
    return Engine.new_game(seed, TableRuleset(config or RuleConfig()), dealer)


def pass_others(engine, keep):
    while engine.state.phase == Phase.CLAIM_WINDOW:
        todo = [s for s in engine.awaiting() if s not in keep]
        if not todo:
            return
        assert engine.apply(Pass(todo[0])).allowed


def test_initial_phase_and_turn_guards():
    e = new()
    assert e.state.phase == Phase.DISCARD and e.state.current_seat == "A"
    r = e.apply(Draw("A"))
    assert not r.allowed and r.reason_code == "wrong_phase"
    r = e.apply(Draw("B"))
    assert not r.allowed and r.reason_code == "not_your_turn"
    r = e.apply(Discard("B", e.state.hands["B"][0]))
    assert not r.allowed and r.reason_code == "not_your_turn"
    r = e.apply(Discard("A", e.state.hands["B"][0]))
    assert not r.allowed and r.reason_code == "card_not_in_hand"
    assert e.action_log == []


def test_claim_without_right_is_rejected_and_claimed_card_leaves_discard():
    e = new()
    rig(e, {"A": [XE[0]], "B": [XE[1]], "C": [XE[2]]})
    move_to_stock(e, [XE[3]])
    assert e.apply(Discard("A", XE[0])).allowed
    assert e.state.phase == Phase.CLAIM_WINDOW
    # C không phải nhà kế tiếp nên không được ăn đôi
    res = e.rules.validate_claim(e.state, Claim("C", (XE[2],), MeldKind.PAIR))
    assert not res.allowed and res.reason_code == "kind_not_allowed_for_seat"
    assert not e.apply(Claim("C", (XE[2],), MeldKind.PAIR)).allowed
    # B là nhà kế tiếp: được ăn đôi
    assert "B" in e.awaiting()
    assert e.apply(Claim("B", (XE[1],), MeldKind.PAIR)).allowed
    pass_others(e, keep=set())
    assert e.state.current_seat == "B" and e.state.phase == Phase.DISCARD
    assert e.state.pending_card_id is None
    assert XE[0] not in [ev.card_id for ev in e.state.discard_pile]
    meld = e.state.exposed_melds["B"][-1]
    assert XE[0] in meld.card_ids and meld.kind == MeldKind.PAIR and meld.source_seat == "A"


def test_wrong_kind_and_fake_meld_rejected():
    e = new()
    rig(e, {"A": [XE[0]], "B": [XE[1], "GREEN-CANNON-0"]})
    assert e.apply(Discard("A", XE[0])).allowed
    r = e.apply(Claim("B", ("GREEN-CANNON-0",), MeldKind.PAIR))
    assert not r.allowed and r.reason_code == "not_a_meld"
    r = e.apply(Claim("B", (XE[1],), MeldKind.TRIPLET))
    assert not r.allowed and r.reason_code == "kind_mismatch"


def test_triplet_from_other_seat_beats_next_seat_pair():
    e = new()
    rig(e, {"A": [XE[0]], "B": [XE[1]], "D": [XE[2], XE[3]]})
    assert e.apply(Discard("A", XE[0])).allowed
    assert {"B", "D"} <= set(e.awaiting())
    assert e.apply(Claim("B", (XE[1],), MeldKind.PAIR)).allowed
    assert e.apply(Claim("D", (XE[2], XE[3]), MeldKind.TRIPLET)).allowed
    pass_others(e, keep=set())
    assert e.state.current_seat == "D"
    assert e.state.exposed_melds["D"][-1].kind == MeldKind.TRIPLET
    assert e.state.exposed_melds["B"] == []
    assert XE[1] in e.state.hands["B"]  # quân của B không bị lấy
    assert e.decisions[-1].action == "resolve" and "Khạp" in e.decisions[-1].result.message


def test_no_claim_then_next_seat_draws_from_stock_top():
    e = new()
    a_card = e.state.hands["A"][0]
    move_to_stock(e, [])
    # bắt mọi nhà bỏ quyền nếu có
    assert e.apply(Discard("A", a_card)).allowed
    pass_others(e, keep=set())
    assert e.state.phase == Phase.DRAW_FROM_STOCK and e.state.current_seat == "B"
    assert e.state.discard_pile[-1].card_id == a_card
    top = e.state.stock[0]
    assert e.apply(Draw("B")).allowed
    assert e.state.pending_card_id == top and e.state.pending_origin == "draw"
    assert e.state.phase in (Phase.EVALUATE, Phase.CLAIM_WINDOW, Phase.DRAW_FROM_STOCK)


def test_khap_lock_when_profile_forbids_split():
    locked = new(config=RuleConfig(forbid_split_khap=True))
    rig(locked, {"A": XE[:3]})
    r = locked.apply(Discard("A", XE[0]))
    assert not r.allowed and r.reason_code == "khap_locked"
    free = new()
    rig(free, {"A": XE[:3]})
    assert free.apply(Discard("A", XE[0])).allowed


@pytest.mark.parametrize("initial,expected", [(True, "dealt"), (False, "formed")])
def test_khap_provenance(initial, expected):
    e = new()
    rig(e, {"A": [XE[0]], "C": [XE[1], XE[2]]}, initial=initial)
    if not initial:
        e.state.initial_hands["C"] = [i for i in e.state.initial_hands["C"] if i not in XE]
    assert e.apply(Discard("A", XE[0])).allowed
    assert e.apply(Claim("C", (XE[1], XE[2]), MeldKind.TRIPLET)).allowed
    pass_others(e, keep=set())
    meld = e.state.exposed_melds["C"][-1]
    assert meld.provenance == expected


def test_mandatory_claim_blocks_pass():
    e = new(config=RuleConfig(mandatory_pair_claim=True))
    rig(e, {"A": [XE[0]], "C": [XE[1], XE[2]]})
    assert e.apply(Discard("A", XE[0])).allowed
    r = e.apply(Pass("C"))
    assert not r.allowed and r.reason_code == "mandatory_claim"


@pytest.mark.parametrize("mode", ["warn_only", "enforce"])
def test_increase_trash_policy(mode):
    e = new(config=RuleConfig(no_increase_trash=mode))
    # B giữ Xe đỏ×2 (đôi) + Mã đỏ×2 (đôi). Ăn Pháo đỏ thành Xe-Pháo-Mã sẽ làm vỡ hai đôi → tăng rác.
    rig(e, {"A": ["RED-CANNON-0"], "B": ["RED-CHARIOT-0", "RED-CHARIOT-1", "RED-HORSE-0", "RED-HORSE-1"]})
    move_to_stock(e, ["RED-CHARIOT-2", "RED-CHARIOT-3", "RED-HORSE-2", "RED-HORSE-3", "RED-CANNON-1", "RED-CANNON-2", "RED-CANNON-3"])
    # Xét ngay khi quân vừa ra (trước khi engine đóng cửa sổ ăn)
    e.state.hands["A"].remove("RED-CANNON-0")
    e.state.pending_card_id, e.state.pending_from, e.state.phase = "RED-CANNON-0", "A", Phase.CLAIM_WINDOW
    cch = [o for o in e.rules.evaluate_claims(e.state, "B") if o.claim.kind == MeldKind.ODD_CCH]
    assert len(cch) == 1 and cch[0].can_form
    assert cch[0].trash_after > cch[0].trash_before
    if mode == "enforce":
        assert not cch[0].allowed and cch[0].reason_code == "increase_trash"
    else:
        assert cch[0].allowed and cch[0].warning


WIN_HAND_B = [
    "RED-CHARIOT-1",
    "RED-GENERAL-0", "RED-ADVISOR-0", "RED-ELEPHANT-0",
    "GREEN-CHARIOT-0", "GREEN-CHARIOT-1", "GREEN-CHARIOT-2",
    "GREEN-CANNON-0", "GREEN-CANNON-1", "GREEN-CANNON-2",
    "GREEN-HORSE-0", "GREEN-HORSE-1", "GREEN-HORSE-2",
    "RED-PAWN-0", "GREEN-PAWN-0", "YELLOW-PAWN-0",
    "YELLOW-HORSE-0", "YELLOW-HORSE-1",
    "YELLOW-CANNON-0", "YELLOW-CANNON-1",
]


def test_claim_that_completes_hand_wins_round():
    e = new()
    set_hand(e, "B", WIN_HAND_B)
    rig(e, {"A": [XE[0]]})
    assert e.rules.trash(e.rules.hand(e.state, "B")) == 1
    assert e.apply(Discard("A", XE[0])).allowed
    opts = e.rules.evaluate_claims(e.state, "B")
    win = [o for o in opts if o.wins]
    assert win and win[0].allowed
    assert e.apply(win[0].claim).allowed
    pass_others(e, keep=set())
    assert e.state.phase == Phase.ROUND_END and e.state.winner == "B"
    assert e.state.scores["B"] == 1
    assert e.apply(Draw("C")).reason_code == "round_over"


def test_bots_take_real_turns_and_game_ends():
    e = new(seed=11)
    bots = {s: Bot("medium") for s in SEATS}
    steps = 0
    while not e.over:
        seat = e.awaiting()[0]
        action, reason = bots[seat].decide(e, seat)
        assert reason
        assert e.apply(action).allowed
        steps += 1
        assert steps < 2000
    actors = {a["seat"] for a in e.action_log}
    assert len(actors) >= 2
    assert e.state.phase == Phase.ROUND_END


def test_profiles_load():
    assert load_ruleset("training_basic").config.ruleset == "training_basic"
    fam = load_ruleset("family_nhatrang")
    assert fam.config.forbid_split_khap and fam.config.mandatory_pair_claim
    with pytest.raises(ValueError, match="chưa được triển khai"):
        load_ruleset("reference_vinagames")
    with pytest.raises(ValueError):
        RuleConfig.from_mapping({"no_increase_trash": "maybe"})
    with pytest.raises(ValueError):
        RuleConfig.from_mapping({"unknown_option": True})
