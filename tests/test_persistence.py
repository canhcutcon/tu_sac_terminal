import json

import pytest

from tusac.bots import Bot
from tusac.engine import Engine
from tusac.models import SEATS
from tusac.persistence import SaveError, load_game, replay, safe_save_path, save_game, to_payload
from tusac.rules import load_ruleset


def played(seed=21, steps=30):
    rules = load_ruleset("training_basic")
    e = Engine.new_game(seed, rules, "A")
    bots = {s: Bot("medium") for s in SEATS}
    for _ in range(steps):
        if e.over:
            break
        seat = e.awaiting()[0]
        action, _ = bots[seat].decide(e, seat)
        assert e.apply(action).allowed
    return e


def test_save_load_round_trip(tmp_path):
    e = played()
    path = save_game(e, safe_save_path("van1", tmp_path), {"human": "D"})
    loaded, meta = load_game(path)
    assert loaded.state.to_dict() == e.state.to_dict()
    assert loaded.action_log == e.action_log
    assert loaded.state.seed == e.state.seed
    assert meta == {"human": "D"}


def test_replay_same_seed_and_actions_gives_same_result():
    e = played(seed=99, steps=500)
    again = replay(99, load_ruleset("training_basic"), "A", e.action_log)
    assert again.state.to_dict() == e.state.to_dict()
    assert again.state.winner == e.state.winner


def test_schema_version_checked(tmp_path):
    e = played()
    payload = to_payload(e)
    payload["schema_version"] = 999
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(SaveError, match="schema_version"):
        load_game(p)


def test_tampered_save_is_rejected(tmp_path):
    e = played()
    payload = to_payload(e)
    payload["state"]["hands"]["A"] = payload["state"]["hands"]["B"]
    p = tmp_path / "tamper.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(SaveError, match="KHÔNG khớp"):
        load_game(p)


def test_illegal_action_in_save_is_rejected(tmp_path):
    e = played()
    payload = to_payload(e)
    payload["actions"].insert(0, {"type": "draw", "seat": "C"})
    p = tmp_path / "illegal.json"
    p.write_text(json.dumps(payload))
    with pytest.raises(SaveError):
        load_game(p)


@pytest.mark.parametrize("name", ["../evil", "/etc/passwd", "a/b", "..", ".hidden", "x" * 80, "bad name"])
def test_save_path_cannot_escape_save_dir(tmp_path, name):
    with pytest.raises(SaveError):
        safe_save_path(name, tmp_path)


def test_safe_save_path_ok(tmp_path):
    assert safe_save_path("game-1", tmp_path) == (tmp_path / "game-1.json").resolve()
