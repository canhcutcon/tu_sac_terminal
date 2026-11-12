"""Simulation: 1.000 ván seed cố định, kiểm bất biến 112 quân sau MỌI action (engine strict=True)."""
from tusac.bots import Bot
from tusac.engine import Engine
from tusac.models import SEATS
from tusac.rules import load_ruleset
from tusac.rules.training import TableRuleset

LEVEL_MIX = [
    {"A": "medium", "B": "medium", "C": "medium", "D": "medium"},
    {"A": "easy", "B": "medium", "C": "easy", "D": "medium"},
]


def _play(seed: int, rules: TableRuleset, levels: dict[str, str]) -> Engine:
    bots = {s: Bot(levels[s]) for s in SEATS}
    engine = Engine.new_game(seed, rules, SEATS[seed % 4], strict=True)
    steps = 0
    while not engine.over:
        seat = engine.awaiting()[0]
        action, _ = bots[seat].decide(engine, seat)
        result = engine.apply(action)  # check_invariants() chạy bên trong
        assert result.allowed, (seed, result)
        steps += 1
        assert steps < 2000, f"deadlock seed {seed}"
    return engine


def test_thousand_games_keep_112_card_invariant():
    rules = load_ruleset("training_basic")
    outcomes = {"win": 0, "draw": 0}
    for seed in range(1000):
        engine = _play(seed, rules, LEVEL_MIX[seed % 2])
        ids = engine.all_cards_in_zones()
        assert len(ids) == 112 and len(set(ids)) == 112
        outcomes["win" if engine.state.winner else "draw"] += 1
    assert outcomes["win"] > 0


def test_strict_family_profile_runs_without_deadlock():
    rules = load_ruleset("family_nhatrang")
    for seed in range(200):
        _play(seed, rules, LEVEL_MIX[seed % 2])
