"""Chơi trọn ván qua parser lệnh của CLI (người chơi được điều khiển bằng gợi ý của bot Medium)."""
import io

from rich.console import Console

from tusac.bots import Bot
from tusac.cli import MAX_INPUT, Session, main
from tusac.models import SEATS, Claim, Discard, Draw, Pass
from tusac.rules import load_ruleset


def make_session(tmp_path, seed=5, human="D", ready=True):
    console = Console(file=io.StringIO(), width=120, force_terminal=False)
    levels = {s: "medium" for s in SEATS}
    session = Session(console, load_ruleset("training_basic"), seed=seed, human=human, dealer="A",
                      bot_levels=levels, save_dir=tmp_path)
    if ready:
        session.handle("ready")
    return session


def command_for(session, action):
    if isinstance(action, Discard):
        return f"discard {session.index_of(action.card_id)}"
    if isinstance(action, Draw):
        return "draw"
    if isinstance(action, Pass):
        return "pass"
    assert isinstance(action, Claim)
    return "claim " + " ".join(str(session.index_of(i)) for i in action.card_ids)


def play_through(session, limit=1000):
    advisor = Bot("medium")
    for _ in range(limit):
        session.run_bots()
        if session.engine.over:
            return
        action, _ = advisor.decide(session.engine, session.human)
        before = len(session.engine.action_log)
        session.handle(command_for(session, action))
        assert len(session.engine.action_log) == before + 1, session.console.file.getvalue()[-2000:]
    raise AssertionError("ván không kết thúc")


def test_full_games_via_commands(tmp_path):
    for seed in range(1, 21):
        s = make_session(tmp_path, seed=seed, human=SEATS[seed % 4])
        play_through(s)
        assert s.engine.over


def test_info_commands_do_not_change_state(tmp_path):
    s = make_session(tmp_path)
    s.run_bots()
    snapshot = s.engine.state.to_dict()
    for cmd in ("help", "hand", "table", "hint", "why", "history 5", "rules", "", "foo", "discard 999", "claim 1 2"):
        s.handle(cmd)
    assert s.engine.state.to_dict() == snapshot


def test_input_is_bounded(tmp_path):
    s = make_session(tmp_path)
    s.run_bots()
    before = s.engine.state.to_dict()
    s.handle("discard " + "1" * MAX_INPUT)
    s.handle("x 1 2 3 4 5 6 7 8 9 10")
    assert s.engine.state.to_dict() == before
    assert "quá dài" in s.console.file.getvalue()


def test_undo_restores_previous_state(tmp_path):
    s = make_session(tmp_path)
    s.run_bots()
    before = s.engine.state.to_dict()
    action, _ = Bot("medium").decide(s.engine, s.human)
    s.handle(command_for(s, action))
    assert s.engine.state.to_dict() != before
    s.handle("undo")
    assert s.engine.state.to_dict() == before


def test_save_and_load_commands(tmp_path):
    s = make_session(tmp_path, seed=8)
    s.run_bots()
    action, _ = Bot("medium").decide(s.engine, s.human)
    s.handle(command_for(s, action))
    s.run_bots()
    state = s.engine.state.to_dict()
    s.handle("save test_save")
    assert (tmp_path / "test_save.json").exists()
    s.handle("new --seed 77")
    assert s.engine.state.seed == 77
    s.handle("load test_save")
    assert s.engine.state.to_dict() == state
    s.handle("save ../escape")
    assert not (tmp_path.parent / "escape.json").exists()


def test_sim_entrypoint(capsys):
    assert main(["--sim", "5", "--seed", "1"]) == 0
    assert "Đã chạy 5 ván" in capsys.readouterr().out


def test_game_waits_until_ready(tmp_path):
    s = make_session(tmp_path, human="B", ready=False)  # A (bot) là nhà cái, đi trước
    assert not s.ready
    s.handle("discard 1")
    assert s.engine.action_log == []  # chưa ready thì không được chơi
    s.handle("sort meld")
    s.handle("swap 1 2")
    s.handle("move 3 1")
    assert s.engine.action_log == []  # xếp bài không phải nước đi
    s.handle("ready")
    s.run_bots()
    assert s.engine.action_log  # bot đã bắt đầu đánh sau khi ready


def test_arrangement_modes_and_moves(tmp_path):
    s = make_session(tmp_path, ready=False)
    hand = sorted(s.engine.state.hands["D"])
    for mode in ("color", "rank", "meld"):
        s.handle(f"sort {mode}")
        assert s.arrangement.mode == mode
        assert sorted(s.hand_ids()) == hand  # mọi quân xuất hiện đúng một lần
    before = s.hand_ids()
    s.handle("move 5 1")
    after = s.hand_ids()
    assert s.arrangement.mode == "free"
    assert after[0] == before[4] and sorted(after) == sorted(before)
    s.handle("swap 1 2")
    assert s.hand_ids()[:2] == [after[1], after[0]]
    s.handle("move 99 1")
    assert "không hợp lệ" in s.console.file.getvalue()


def test_custom_order_survives_play_and_drives_indices(tmp_path):
    s = make_session(tmp_path, seed=9, ready=False)
    s.handle("move 20 1")
    first = s.hand_ids()[0]
    s.handle("ready")
    play_through(s)  # chơi hết ván bằng số thứ tự theo cách xếp tự do
    assert s.engine.over
    assert s.arrangement.mode == "free"
    assert first in s.arrangement.custom or first not in s.engine.state.hands["D"]


def test_arrangement_saved_and_loaded(tmp_path):
    s = make_session(tmp_path, ready=False)
    s.handle("swap 1 3")
    order = s.hand_ids()
    s.handle("ready")
    s.handle("save arr")
    s.handle("new")
    s.handle("load arr")
    assert s.ready and s.hand_ids() == order


def test_names_toggle(tmp_path):
    s = make_session(tmp_path, ready=False)
    s.console.file.truncate(0)
    s.cmd_hand([])
    compact = s.console.file.getvalue()
    assert "將" in compact or "士" in compact
    assert " đỏ" not in compact and " xanh" not in compact
    s.handle("names on")
    assert s.names
    s.console.file.truncate(0)
    s.cmd_hand([])
    assert any(w in s.console.file.getvalue() for w in (" đỏ", " xanh", " vàng", " trắng"))


def test_meld_area_build_split_check(tmp_path):
    s = make_session(tmp_path, seed=42, ready=False)
    s.handle("sort meld")
    a = s.arrangement
    assert a.mode == "meld" and a.groups
    rep = a.check(s.engine, "D")
    assert rep.loose == rep.optimal_trash  # tự xếp = tối ưu
    n_groups = len(a.groups)
    s.handle("tach all")
    assert a.groups == []
    # gom tay: lấy 1 bộ hợp lệ do máy tìm, tìm số thứ tự hiện tại rồi `bo`
    s.handle("sort meld")
    target = a.groups[0]
    s.handle("tach 1")
    assert len(a.groups) == n_groups - 1
    nums = [str(s.index_of(i)) for i in target]
    s.handle("bo " + " ".join(nums))
    assert a.groups[-1] == target
    assert "Đã gom bộ" in s.console.file.getvalue()
    s.handle("check")
    assert "KIỂM TRA BÀI" in s.console.file.getvalue()
    assert s.engine.action_log == []  # xếp bộ không phải nước đi
    assert sorted(s.hand_ids()) == sorted(s.engine.state.hands["D"])


def test_invalid_group_marked(tmp_path):
    s = make_session(tmp_path, seed=42, ready=False)
    s.handle("sort color")
    hand = s.hand_ids()
    # hai quân khác loại khác màu → không hợp lệ
    from tusac.deck import card
    i, j = next((x, y) for x in range(len(hand)) for y in range(x + 1, len(hand))
                if card(hand[x]).kind != card(hand[y]).kind and card(hand[x]).rank != card(hand[y]).rank)
    s.handle(f"bo {i + 1} {j + 1}")
    rep = s.arrangement.check(s.engine, "D")
    assert not rep.lines[-1][1]
