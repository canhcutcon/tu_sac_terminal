"""Giao diện dòng lệnh: vòng lặp chơi, parser lệnh, demo/simulation."""
from __future__ import annotations

import argparse
import copy
import random
import sys
import time
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .bots import LEVELS, Bot
from .deck import card, cards
from .engine import Engine
from .melds import identify_meld
from .models import MELD_VI, SEATS, Action, Claim, Discard, Draw, Pass, Phase, next_seat
from .persistence import SaveError, load_game, safe_save_path, save_game
from .arrange import MODE_VI, MODES, HandArrangement, group_kind
from .render import card_label, card_text, render_hand_rows, render_table
from .rules import load_ruleset
from .rules.training import TableRuleset
from .trainer import group_label, hint, why

MAX_INPUT = 200
MAX_TOKENS = 8
SEAT_STYLE = {"A": "magenta", "B": "blue", "C": "green", "D": "yellow"}

HELP = """\
[bold]Xếp bài (trước ván và bất cứ lúc nào)[/bold]
  sort color            Xếp theo màu (mặc định)
  sort rank             Xếp theo loại quân (Tướng, Sĩ, ... Tốt)
  sort meld             Mở KHU VỰC XẾP BỘ và tự xếp bộ tối ưu (rác / chờ để cuối)
  bo 3 7 9              Gom quân số 3, 7, 9 thành một bộ (tự xếp bộ bằng tay)
  tach 2 / tach all     Tách bộ 2 (hoặc tất cả) trả về Rác / chờ
  check                 Kiểm tra bài: bộ nào hợp lệ, còn bao nhiêu rác, xếp đã tối ưu chưa
  move 5 1              Chuyển quân số 5 lên vị trí 1 (chuyển sang chế độ tự xếp)
  swap 3 8              Đổi chỗ quân số 3 và số 8
  names on|off          Bật/tắt tên tiếng Việt trên quân (mặc định tắt: chỉ chữ Hán + màu)
  ready (r)             Sẵn sàng — bắt đầu ván (các nhà bot chỉ chơi sau khi bạn ready)

[bold]Lệnh trong ván[/bold]
  hand (h)              Hiện bài của bạn kèm số thứ tự
  table (t)             Hiện cả bàn: nọc, lượt, bộ mở, quân vừa đánh
  discard 4 (x 4)       Đánh quân số 4
  claim 3 7 (c 3 7)     Ăn quân đang chờ bằng quân số 3 và 7 trên tay
  claim a / claim       Ăn theo lựa chọn a, b, ... đã liệt kê (claim trống = liệt kê / chọn nếu chỉ có 1)
  pass (p)              Bỏ quyền ăn / bỏ quân vừa bốc
  draw (d)              Bốc nọc (khi tới lượt bốc)
  hint                  Gợi ý + giải thích (không tự chơi giùm)
  why                   Giải thích các quyết định luật gần nhất
  history 10            Xem 10 sự kiện gần nhất
  rules                 Xem profile luật đang bật
  undo (u)              Hoàn tác nước vừa rồi (chế độ luyện tập)
  save ten_file         Lưu ván vào thư mục save
  load ten_file         Nạp ván (dựng lại theo seed + action và xác minh)
  new [--seed 42]       Ván mới
  quit (q)              Thoát

[bold]Luật tóm tắt (training_basic)[/bold]
  • 112 quân: 4 màu (Đỏ, Xanh, Vàng, Trắng) × 7 loại (Tướng Sĩ Tượng Xe Pháo Mã Tốt) × 4.
  • Phe: Đôi / Khạp (3 giống) / Quàn (4 giống); Tướng-Sĩ-Tượng hoặc Xe-Pháo-Mã cùng màu;
    3 hoặc 4 Tốt khác màu. Tướng đứng một mình không tính là rác.
  • Tới khi mọi quân trên tay đều thành phe (không còn rác).
  • Lượt: người kế tiếp được ăn quân vừa đánh để ghép bất kỳ bộ nào; nhà khác chỉ ăn được
    thành Khạp/Quàn (hoặc để tới). Không ai ăn → người kế tiếp bốc nọc; quân bốc được nếu
    không dùng thì để lại cho các nhà khác ăn.
  • Ưu tiên: Tới > Quàn > Khạp > bộ khác; cùng hạng thì nhà gần người đánh hơn.
  • Hết nọc chưa ai tới → hòa. Đây là luật LUYỆN TẬP, không phải "luật chuẩn Nha Trang".
"""


class Session:
    def __init__(
        self,
        console: Console,
        rules: TableRuleset,
        *,
        seed: int,
        human: str | None,
        dealer: str,
        bot_levels: dict[str, str],
        ascii_only: bool = False,
        practice: bool = True,
        delay: float = 0.0,
        save_dir: Path = Path("saves"),
        verbose_bots: bool = False,
    ):
        self.console = console
        self.rules = rules
        self.human = human
        self.bot_levels = bot_levels
        self.bots = {seat: Bot(bot_levels[seat]) for seat in SEATS if seat != human}
        self.ascii = ascii_only
        self.practice = practice
        self.delay = delay
        self.save_dir = save_dir
        self.verbose_bots = verbose_bots or human is None
        self.round_no = 0
        self.tally: Counter = Counter()
        self.running = True
        self.arrangement = HandArrangement()
        self.names = False  # quân bài chỉ hiện chữ Hán tô màu; `names on` để hiện thêm tên tiếng Việt
        self.start_round(seed, dealer)

    # ------------------------------------------------------------ round lifecycle

    def start_round(self, seed: int, dealer: str) -> None:
        self.engine = Engine.new_game(seed, self.rules, dealer)
        self.round_no += 1
        self.printed = 0
        self.snapshots: list[tuple] = []
        self.bot_reasons: dict[str, str] = {}
        self.scored = False
        self.need_render = True
        self.ready = self.human is None  # người chơi xếp bài xong, gõ ready mới bắt đầu
        if self.arrangement.mode == "free":
            self.arrangement.custom = []
        self.arrangement.groups = []
        self.console.print()
        self.console.rule(f"[bold cyan]Ván #{self.round_no} — seed {seed} — nhà cái {dealer}")
        self.flush_events()

    def next_round(self, seed: int | None = None) -> None:
        s = self.engine.state
        dealer = s.winner or next_seat(s.dealer)
        self.start_round(s.seed + 1 if seed is None else seed, dealer)

    # ------------------------------------------------------------ output helpers

    def label(self, cid: str) -> str:
        if self.human and cid in self.engine.state.hands[self.human]:
            return f"[{self.index_of(cid):02d}] {card_label(card(cid), self.ascii)}"
        return card_label(card(cid), self.ascii)

    def hand_ids(self) -> list[str]:
        assert self.human
        return self.arrangement.order(self.engine, self.human)

    def index_of(self, cid: str) -> int:
        return self.hand_ids().index(cid) + 1

    def hand_view(self):
        assert self.human
        rows = self.arrangement.rows(self.engine, self.human)
        order = [cid for _, _, ids, _ in rows for cid in ids]
        return render_hand_rows(rows, order, self.ascii, width=max(40, self.console.width - 6), names=self.names)

    def info(self, msg: str, style: str = "") -> None:
        self.console.print(Text(msg, style=style))

    def flush_events(self) -> None:
        history = self.engine.state.history
        for ev in history[self.printed :]:
            style = SEAT_STYLE.get(ev.seat or "", "")
            prefix = "★ " if ev.kind in ("claim", "round_end") else "• "
            line = Text(prefix)
            line.append(ev.text, style=f"bold {style}" if ev.kind in ("claim", "round_end") else style)
            self.console.print(line)
            if ev.kind == "claim" and ev.seat in self.bot_reasons:
                self.info(f"    ↳ lý do của bot {ev.seat}: {self.bot_reasons.pop(ev.seat)}", "dim")
        self.printed = len(history)

    # ------------------------------------------------------------ bots

    def run_bots(self) -> None:
        e = self.engine
        while not e.over:
            todo = [s for s in e.awaiting() if s != self.human]
            if not todo:
                return
            seat = todo[0]
            action, reason = self.bots[seat].decide(e, seat)
            result = e.apply(action)
            if not result.allowed:  # không bao giờ nên xảy ra — bot dùng cùng Ruleset
                raise RuntimeError(f"Bot {seat} bị luật từ chối: {result.message}")
            if isinstance(action, Claim):
                self.bot_reasons[seat] = reason
            elif self.verbose_bots and isinstance(action, Discard):
                self.info(f"    ↳ {seat}: {reason}", "dim")
            self.flush_events()
            if self.delay:
                time.sleep(self.delay)

    # ------------------------------------------------------------ prompt / render

    def claim_options(self):
        assert self.human
        return [o for o in self.rules.evaluate_claims(self.engine.state, self.human) if o.allowed]

    def prompt_text(self) -> Text:
        e, me = self.engine, self.human
        s = e.state
        t = Text()
        if not self.ready:
            t.append("✋ XẾP BÀI trước khi chơi", style="bold yellow")
            t.append(f" (đang xếp {MODE_VI[self.arrangement.mode]})\n")
            t.append("   sort color | sort rank | sort meld   ·   bo 3 7 9 | tach 2 | check   ·   move 5 1 | swap 2 8\n")
            t.append("   → gõ ", style="dim")
            t.append("ready", style="bold green")
            t.append(" khi sẵn sàng để bắt đầu ván", style="dim")
            return t
        if e.over:
            t.append("Ván đã kết thúc → new | history | save <tên> | quit", style="bold")
            return t
        if me not in e.awaiting():
            t.append(f"Đang chờ {', '.join(e.awaiting())}...", style="dim")
            return t
        if s.phase == Phase.DISCARD:
            t.append("▶ Lượt bạn ĐÁNH: ", style="bold green")
            t.append("discard <số>   |  hint  |  help")
        elif s.phase == Phase.DRAW_FROM_STOCK:
            t.append("▶ Không ai ăn. Lượt bạn BỐC: ", style="bold green")
            t.append("draw (d)   |  hint  |  help")
        else:
            pending = card(s.pending_card_id)  # type: ignore[arg-type]
            verb = "vừa bốc" if s.phase == Phase.EVALUATE else "vừa ra"
            t.append(f"▶ Quân {verb}: ", style="bold green")
            t.append_text(card_text(pending, self.ascii))
            t.append(" — bạn có thể ăn:\n", style="bold green")
            for n, o in enumerate(self.claim_options()):
                letter = chr(ord("a") + n)
                used = " + ".join(self.label(i) for i in o.claim.card_ids)
                t.append(f"   {letter}) {MELD_VI[o.claim.kind]}: {used} + {card_label(pending, self.ascii)}")
                t.append(f"  [rác {o.trash_before}→{o.trash_after}]", style="dim")
                if o.wins:
                    t.append("  ★ TỚI", style="bold magenta")
                if o.mandatory:
                    t.append("  ! BẮT BUỘC", style="bold red")
                if o.warning:
                    t.append(f"  ⚠ {o.warning}", style="yellow")
                t.append("\n")
            t.append("   → claim <chữ> | claim <số> <số> | pass | hint")
        return t

    def render(self) -> None:
        self.console.print(
            render_table(
                self.engine,
                self.human,
                ascii_only=self.ascii,
                round_no=self.round_no,
                tally=self.tally,
                prompt=self.prompt_text(),
                hand_view=self.hand_view() if self.human else None,
                hand_title=self.arrangement.title(self.engine, self.human) if self.human else "",
                names=self.names,
            )
        )

    def show_round_end(self) -> None:
        s = self.engine.state
        if s.winner:
            self.tally[s.winner] += 1
        self.console.rule("[bold magenta]KẾT THÚC VÁN")
        self.info(s.end_reason, "bold magenta")
        table = Table(title="Bài trên tay lúc hết ván", show_lines=False)
        table.add_column("Nhà")
        table.add_column("Rác", justify="right")
        table.add_column("Phe trên tay / quân rác")
        for seat in SEATS:
            a = self.engine.hand_analysis(seat)
            body = Text()
            for g, cs in a.groups:
                body.append(f"[{group_label(g)}: {' '.join(c.name_vi() for c in cs)}] ")
            if a.trash:
                body.append("rác: " + ", ".join(c.name_vi() for c in a.trash), style="red")
            who = f"{seat}{' (bạn)' if seat == self.human else ''}{' ★' if seat == s.winner else ''}"
            table.add_row(who, str(a.trash_count), body)
        self.console.print(table)
        tally = "  ".join(f"{seat}: {self.tally[seat]}" for seat in SEATS)
        self.info(f"Tổng số ván thắng: {tally}", "bold")

    # ------------------------------------------------------------ main loop

    def loop(self) -> None:
        self.console.print(Text("Gõ `help` để xem lệnh. Chúc vui!", style="dim"))
        while self.running:
            if self.ready:
                self.run_bots()
            if self.engine.over and not self.scored:
                self.scored = True
                self.show_round_end()
                self.info("Gõ `new` để chơi ván tiếp, `quit` để thoát.", "dim")
                self.need_render = False
            elif self.need_render and not self.engine.over:
                self.render()
                self.need_render = False
            try:
                line = self.console.input("[bold cyan]> [/]")
            except (EOFError, KeyboardInterrupt):
                self.console.print()
                break
            self.handle(line)
        self.info("Tạm biệt!", "dim")

    # ------------------------------------------------------------ commands

    def act(self, action: Action) -> bool:
        e = self.engine
        snap = (copy.deepcopy(e.state), list(e.action_log), list(e.decisions), self.printed)
        in_window = e.state.phase == Phase.CLAIM_WINDOW
        result = e.apply(action)
        if not result.allowed:
            self.info(f"✗ {result.message}", "bold red")
            return False
        if self.practice:
            self.snapshots.append(snap)
        if isinstance(action, Claim) and in_window:
            self.info("✓ Đã đề nghị ăn — chờ các nhà khác quyết định rồi phân xử.", "green")
            if result.message:
                self.info(f"  {result.message}", "dim")
        self.flush_events()
        self.need_render = True
        return True

    def handle(self, line: str) -> None:
        if len(line) > MAX_INPUT:
            self.info(f"Lệnh quá dài (tối đa {MAX_INPUT} ký tự).", "red")
            return
        tokens = line.strip().split()
        if not tokens:
            self.need_render = True
            return
        if len(tokens) > MAX_TOKENS:
            self.info("Quá nhiều tham số.", "red")
            return
        cmd, args = tokens[0].lower(), tokens[1:]
        aliases = {"h": "hand", "t": "table", "x": "discard", "c": "claim", "p": "pass", "d": "draw",
                   "u": "undo", "q": "quit", "exit": "quit", "?": "help", "r": "ready", "xep": "sort",
                   "group": "bo", "split": "tach", "kiemtra": "check"}
        cmd = aliases.get(cmd, cmd)
        handler = getattr(self, f"cmd_{cmd}", None)
        if handler is None:
            self.info(f"Không hiểu lệnh {cmd!r}. Gõ `help`.", "red")
            return
        try:
            handler(args)
        except SaveError as exc:
            self.info(f"✗ {exc}", "bold red")

    def _need_human(self) -> bool:
        if self.human is None:
            self.info("Chế độ demo: không có người chơi.", "red")
            return False
        if self.engine.over:
            self.info("Ván đã kết thúc. Gõ `new`.", "red")
            return False
        if not self.ready:
            self.info("Bạn đang xếp bài — gõ `ready` để bắt đầu ván.", "yellow")
            return False
        return True

    def _parse_index(self, raw: str) -> str | None:
        ids = self.hand_ids()
        if not raw.isdigit() or not 1 <= int(raw) <= len(ids):
            self.info(f"Số thứ tự {raw!r} không hợp lệ (1..{len(ids)}).", "red")
            return None
        return ids[int(raw) - 1]

    def cmd_help(self, args: list[str]) -> None:
        self.console.print(HELP)

    def cmd_hand(self, args: list[str]) -> None:
        if self.human:
            self.console.print(self.hand_view())

    def cmd_table(self, args: list[str]) -> None:
        self.render()

    def cmd_discard(self, args: list[str]) -> None:
        if not self._need_human():
            return
        if len(args) != 1:
            self.info("Cú pháp: discard <số>", "red")
            return
        cid = self._parse_index(args[0])
        if cid:
            self.act(Discard(self.human, cid))  # type: ignore[arg-type]

    def cmd_draw(self, args: list[str]) -> None:
        if self._need_human():
            self.act(Draw(self.human))  # type: ignore[arg-type]

    def cmd_pass(self, args: list[str]) -> None:
        if self._need_human():
            self.act(Pass(self.human))  # type: ignore[arg-type]

    def cmd_claim(self, args: list[str]) -> None:
        if not self._need_human():
            return
        e, me = self.engine, self.human
        assert me
        if me not in e.awaiting() or e.state.phase not in (Phase.CLAIM_WINDOW, Phase.EVALUATE):
            self.info("Không có quân nào để bạn ăn lúc này.", "red")
            return
        options = self.claim_options()
        if not args:
            if len(options) == 1:
                self.act(options[0].claim)
            else:
                self.render()
            return
        if len(args) == 1 and len(args[0]) == 1 and args[0].isalpha():
            n = ord(args[0].lower()) - ord("a")
            if not 0 <= n < len(options):
                self.info("Không có lựa chọn đó.", "red")
                return
            self.act(options[n].claim)
            return
        if len(args) > 3:
            self.info("Chỉ chọn tối đa 3 quân trên tay.", "red")
            return
        ids = [self._parse_index(a) for a in args]
        if any(i is None for i in ids):
            return
        pending = card(e.state.pending_card_id)  # type: ignore[arg-type]
        kind = identify_meld(cards(ids) + [pending], self.rules.meld_rules)  # type: ignore[arg-type]
        if kind is None:
            names = " + ".join(c.name_vi() for c in cards(ids) + [pending])  # type: ignore[arg-type]
            self.info(f"✗ {names} không tạo thành bộ hợp lệ.", "bold red")
            return
        self.act(Claim(me, tuple(ids), kind))  # type: ignore[arg-type]

    def cmd_hint(self, args: list[str]) -> None:
        if not self.human:
            return
        for line in hint(self.engine, self.human, self.label, self.index_of):
            self.info(line, "cyan")

    def cmd_why(self, args: list[str]) -> None:
        for line in why(self.engine):
            self.info(line, "cyan")

    def cmd_history(self, args: list[str]) -> None:
        n = 10
        if args:
            if not args[0].isdigit():
                self.info("Cú pháp: history <số>", "red")
                return
            n = max(1, min(200, int(args[0])))
        for ev in self.engine.state.history[-n:]:
            self.info(f"  #{ev.turn_no:>3} {ev.text}")

    def cmd_rules(self, args: list[str]) -> None:
        table = Table(title=f"Profile luật: {self.rules.id}")
        table.add_column("Tùy chọn", style="cyan")
        table.add_column("Giá trị", style="bold")
        table.add_column("Ý nghĩa")
        for key, value, meaning in self.rules.describe():
            table.add_row(key, value, meaning)
        self.console.print(table)
        self.info("Các giá trị trên là lựa chọn kỹ thuật cho chế độ học, KHÔNG phải tuyên bố luật Tứ Sắc truyền thống.", "dim")

    def cmd_undo(self, args: list[str]) -> None:
        if not self.practice:
            self.info("Undo chỉ có trong chế độ luyện tập.", "red")
            return
        if not self.snapshots:
            self.info("Không còn gì để hoàn tác.", "red")
            return
        state, log, decisions, printed = self.snapshots.pop()
        self.engine.state, self.engine.action_log, self.engine.decisions = state, log, decisions
        self.printed = printed
        self.scored = False
        self.bot_reasons.clear()
        self.info("↶ Đã hoàn tác nước đi gần nhất của bạn.", "yellow")
        self.need_render = True

    def cmd_save(self, args: list[str]) -> None:
        name = args[0] if args else f"tusac_seed{self.engine.state.seed}_van{self.round_no}"
        path = safe_save_path(name, self.save_dir)
        meta = {"human": self.human, "bot_levels": self.bot_levels, "round_no": self.round_no,
                "tally": dict(self.tally), "arrangement": self.arrangement.to_meta()}
        save_game(self.engine, path, meta)
        self.info(f"✓ Đã lưu {path}", "green")

    def cmd_load(self, args: list[str]) -> None:
        if len(args) != 1:
            self.info("Cú pháp: load <tên_file>", "red")
            return
        engine, meta = load_game(safe_save_path(args[0], self.save_dir))
        human = meta.get("human")
        if human not in SEATS:
            raise SaveError("File save không có thông tin người chơi.")
        levels = meta.get("bot_levels") or {}
        self.human = human
        self.bot_levels = {s: (levels.get(s) if levels.get(s) in LEVELS else "medium") for s in SEATS}
        self.bots = {s: Bot(self.bot_levels[s]) for s in SEATS if s != human}
        self.rules = engine.rules
        self.engine = engine
        self.round_no = int(meta.get("round_no", 1)) if str(meta.get("round_no", 1)).isdigit() else 1
        tally = meta.get("tally") or {}
        self.tally = Counter({s: int(v) for s, v in tally.items() if s in SEATS and isinstance(v, int)})
        self.printed = len(engine.state.history)
        self.snapshots, self.bot_reasons = [], {}
        self.arrangement = HandArrangement.from_meta(meta.get("arrangement"), engine.state.hands[human])
        self.ready = True
        self.scored = engine.over
        self.need_render = True
        self.info(f"✓ Đã nạp và xác minh ván (seed {engine.state.seed}, {len(engine.action_log)} action).", "green")

    def cmd_new(self, args: list[str]) -> None:
        seed = None
        if args:
            raw = args[1] if args[0] == "--seed" and len(args) > 1 else args[0]
            if not raw.lstrip("-").isdigit():
                self.info("Cú pháp: new [--seed <số>]", "red")
                return
            seed = int(raw)
        self.next_round(seed)

    # ------------------------------------------------------------ xếp bài

    def _need_hand(self) -> bool:
        if self.human is None:
            self.info("Chế độ demo: không có bài để xếp.", "red")
            return False
        return True

    def cmd_sort(self, args: list[str]) -> None:
        if not self._need_hand():
            return
        if len(args) != 1 or args[0].lower() not in MODES[:3]:
            self.info("Cú pháp: sort color | sort rank | sort meld", "red")
            return
        mode = args[0].lower()
        if mode == "meld":
            self.arrangement.auto_groups(self.engine, self.human)  # type: ignore[arg-type]
            self.info("↻ Đã tự xếp bộ tối ưu vào khu vực xếp bộ (sửa bằng `bo` / `tach`).", "green")
        else:
            self.arrangement.set_mode(mode)
            self.info(f"↻ Đã xếp bài {MODE_VI[mode]}.", "green")
        self.cmd_hand([])

    def _two_numbers(self, args: list[str], usage: str) -> tuple[int, int] | None:
        if len(args) != 2 or not all(a.isdigit() for a in args):
            self.info(f"Cú pháp: {usage}", "red")
            return None
        return int(args[0]), int(args[1])

    def cmd_move(self, args: list[str]) -> None:
        if not self._need_hand() or (nums := self._two_numbers(args, "move <từ> <đến>")) is None:
            return
        try:
            cid = self.arrangement.move(self.engine, self.human, *nums)  # type: ignore[arg-type]
        except ValueError as exc:
            self.info(str(exc), "red")
            return
        self.info(f"↻ Đã chuyển {card(cid).name_vi()} tới vị trí {nums[1]}.", "green")
        self.cmd_hand([])

    def cmd_swap(self, args: list[str]) -> None:
        if not self._need_hand() or (nums := self._two_numbers(args, "swap <a> <b>")) is None:
            return
        try:
            x, y = self.arrangement.swap(self.engine, self.human, *nums)  # type: ignore[arg-type]
        except ValueError as exc:
            self.info(str(exc), "red")
            return
        self.info(f"↻ Đã đổi chỗ {card(x).name_vi()} ↔ {card(y).name_vi()}.", "green")
        self.cmd_hand([])

    def cmd_bo(self, args: list[str]) -> None:
        if not self._need_hand():
            return
        if not args or not all(a.isdigit() for a in args):
            self.info("Cú pháp: bo <số> <số> ... (1–4 quân)", "red")
            return
        try:
            ids = self.arrangement.make_group(self.engine, self.human, [int(a) for a in args])  # type: ignore[arg-type]
        except ValueError as exc:
            self.info(str(exc), "red")
            return
        kind = group_kind(ids, self.rules.meld_rules)
        names = " + ".join(card(i).name_vi() for i in ids)
        if kind:
            self.info(f"✓ Đã gom bộ: {names} → {kind}", "green")
        else:
            self.info(f"✗ Đã gom: {names} — chưa phải bộ hợp lệ", "yellow")
        self.cmd_hand([])

    def cmd_tach(self, args: list[str]) -> None:
        if not self._need_hand():
            return
        if len(args) != 1:
            self.info("Cú pháp: tach <số bộ> | tach all", "red")
            return
        try:
            n = self.arrangement.split_group(self.engine, self.human, args[0].lower())  # type: ignore[arg-type]
        except ValueError as exc:
            self.info(str(exc), "red")
            return
        self.info(f"↺ Đã tách {n} bộ về Rác / chờ.", "green")
        self.cmd_hand([])

    def cmd_check(self, args: list[str]) -> None:
        if not self._need_hand():
            return
        rep = self.arrangement.check(self.engine, self.human)  # type: ignore[arg-type]
        self.info(f"KIỂM TRA BÀI — {rep.valid_groups} bộ hợp lệ", "bold")
        for line, ok in rep.lines:
            self.info(f"  {'✓' if ok else '✗'} {line}", "green" if ok else "red")
        if not rep.lines:
            self.info("  (chưa gom bộ nào — dùng `bo 3 7 9` hoặc `sort meld`)", "dim")
        self.info(f"  Rác / chờ theo cách xếp của bạn: {rep.loose} quân", "yellow")
        if rep.loose == 0:
            self.info("  ★ Mọi quân đều đã vào bộ hợp lệ — bài TỚI!", "bold magenta")
        elif rep.loose > rep.optimal_trash:
            self.info(f"  Gợi ý: xếp tối ưu chỉ còn {rep.optimal_trash} rác (gõ `sort meld` để xem).", "cyan")
        else:
            self.info("  Cách xếp của bạn đã tối ưu.", "cyan")

    def cmd_names(self, args: list[str]) -> None:
        if len(args) != 1 or args[0].lower() not in ("on", "off"):
            self.info("Cú pháp: names on | names off", "red")
            return
        self.names = args[0].lower() == "on"
        self.info("Hiện tên tiếng Việt trên quân." if self.names else "Chỉ hiện chữ Hán tô màu.", "green")
        self.cmd_hand([])

    def cmd_ready(self, args: list[str]) -> None:
        if self.ready:
            self.info("Ván đang diễn ra rồi.", "dim")
            return
        self.ready = True
        self.need_render = True
        self.info("▶ Sẵn sàng! Bắt đầu ván.", "bold green")

    def cmd_quit(self, args: list[str]) -> None:
        self.running = False


# ---------------------------------------------------------------- demo / simulation


def run_demo(console: Console, rules: TableRuleset, seed: int, dealer: str, levels: dict[str, str], delay: float, ascii_only: bool) -> None:
    session = Session(console, rules, seed=seed, human=None, dealer=dealer, bot_levels=levels,
                      ascii_only=ascii_only, delay=delay)
    session.run_bots()
    session.console.print(render_table(session.engine, None, ascii_only=ascii_only, round_no=1, tally={}))
    session.show_round_end()


def simulate(n: int, seed: int, rules: TableRuleset, levels: dict[str, str]) -> dict[str, int]:
    bots = {s: Bot(levels[s]) for s in SEATS}
    stats: Counter = Counter()
    for k in range(n):
        engine = Engine.new_game(seed + k, rules, SEATS[k % 4])
        steps = 0
        while not engine.over:
            seat = engine.awaiting()[0]
            action, _ = bots[seat].decide(engine, seat)
            if not engine.apply(action).allowed:
                raise RuntimeError(f"seed {seed + k}: action bot bị từ chối")
            steps += 1
            if steps > 2000:
                raise RuntimeError(f"seed {seed + k}: deadlock?")
        stats[engine.state.winner or "hòa"] += 1
        stats["_steps"] += steps
    return dict(stats)


def parse_levels(spec: str, human: str | None) -> dict[str, str]:
    parts = [p.strip().lower() for p in spec.split(",") if p.strip()]
    if not parts or any(p not in LEVELS for p in parts):
        raise ValueError(f"--bots phải là danh sách trong {LEVELS}, ví dụ: easy,medium,medium")
    bot_seats = [s for s in SEATS if s != human]
    if len(parts) == 1:
        parts = parts * len(bot_seats)
    if len(parts) != len(bot_seats):
        raise ValueError(f"Cần 1 hoặc {len(bot_seats)} mức bot.")
    levels = dict(zip(bot_seats, parts))
    if human:
        levels[human] = "medium"
    return levels


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tusac", description="Tứ Sắc trong terminal — 1 người + 3 bot, luật cấu hình được.")
    p.add_argument("--rules", default="training_basic", help="Tên profile (training_basic, family_nhatrang) hoặc đường dẫn .yaml")
    p.add_argument("--seed", type=int, default=None, help="Seed để tái lập ván (mặc định: ngẫu nhiên)")
    p.add_argument("--seat", default="D", choices=SEATS, help="Vị trí của bạn (mặc định D)")
    p.add_argument("--dealer", default="A", choices=SEATS, help="Nhà cái (mặc định A)")
    p.add_argument("--bots", default="medium", help="Mức bot: easy|medium, hoặc 3 mức cách nhau dấu phẩy")
    p.add_argument("--ascii", action="store_true", help="Không dùng chữ Hán và khung Unicode")
    p.add_argument("--no-undo", action="store_true", help="Tắt undo (không phải chế độ luyện tập)")
    p.add_argument("--delay", type=float, default=0.15, help="Giây nghỉ giữa các nước của bot")
    p.add_argument("--save-dir", default="saves", help="Thư mục lưu ván")
    p.add_argument("--demo", action="store_true", help="4 bot tự chơi một ván")
    p.add_argument("--sim", type=int, default=0, metavar="N", help="Chạy N ván 4 bot không hiển thị, in thống kê")
    p.add_argument("--replay", metavar="FILE", help="Phát lại một file save và in lịch sử")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console(highlight=False)
    try:
        rules = load_ruleset(args.rules)
        human = None if (args.demo or args.sim) else args.seat
        levels = parse_levels(args.bots, human)
    except ValueError as exc:
        console.print(f"[bold red]Lỗi:[/] {exc}")
        return 2
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(1, 1_000_000)
    if args.replay:
        try:
            engine, meta = load_game(Path(args.replay))
        except SaveError as exc:
            console.print(f"[bold red]Lỗi:[/] {exc}")
            return 2
        for ev in engine.state.history:
            console.print(f"#{ev.turn_no:>3} {ev.text}")
        console.print(f"[green]Replay khớp snapshot ({len(engine.action_log)} action, seed {engine.state.seed}).")
        return 0
    if args.sim:
        n = max(1, min(args.sim, 100_000))
        t0 = time.perf_counter()
        stats = simulate(n, seed, rules, levels)
        dt = time.perf_counter() - t0
        steps = stats.pop("_steps")
        console.print(f"Đã chạy {n} ván (seed {seed}..{seed + n - 1}) trong {dt:.1f}s, trung bình {steps / n:.0f} action/ván.")
        console.print("Kết quả: " + ", ".join(f"{k}: {v}" for k, v in sorted(stats.items())))
        return 0
    if args.demo:
        run_demo(console, rules, seed, args.dealer, levels, args.delay, args.ascii)
        return 0
    if not sys.stdin.isatty():
        args.delay = 0.0
    session = Session(
        console, rules, seed=seed, human=args.seat, dealer=args.dealer, bot_levels=levels,
        ascii_only=args.ascii, practice=not args.no_undo, delay=args.delay, save_dir=Path(args.save_dir),
    )
    session.loop()
    return 0
