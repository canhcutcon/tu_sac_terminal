import random

import pytest

from tusac.deck import build_deck, card
from tusac.melds import MeldRules, analyze, identify_meld, meld_options_with, trash_count
from tusac.models import Card, Color, MeldKind, Rank

R, G, Y, W = Color.RED, Color.GREEN, Color.YELLOW, Color.WHITE


def c(color, rank, i=0):
    return Card(color, rank, i)


def test_pairs_triplets_quads():
    assert identify_meld([c(R, Rank.PAWN, 0), c(R, Rank.PAWN, 1)]) == MeldKind.PAIR
    assert identify_meld([c(G, Rank.CHARIOT, i) for i in range(3)]) == MeldKind.TRIPLET
    assert identify_meld([c(W, Rank.HORSE, i) for i in range(4)]) == MeldKind.QUAD
    assert identify_meld([c(R, Rank.PAWN, 0), c(G, Rank.PAWN, 0)]) is None  # khác màu không phải đôi


def test_odd_trios_same_color_only():
    assert identify_meld([c(R, Rank.GENERAL), c(R, Rank.ADVISOR), c(R, Rank.ELEPHANT)]) == MeldKind.ODD_GAE
    assert identify_meld([c(Y, Rank.CHARIOT), c(Y, Rank.CANNON), c(Y, Rank.HORSE)]) == MeldKind.ODD_CCH
    assert identify_meld([c(R, Rank.GENERAL), c(G, Rank.ADVISOR), c(R, Rank.ELEPHANT)]) is None
    assert identify_meld([c(R, Rank.CHARIOT), c(R, Rank.CANNON), c(R, Rank.ELEPHANT)]) is None


def test_pawn_sets_need_distinct_colors():
    assert identify_meld([c(R, Rank.PAWN), c(G, Rank.PAWN), c(Y, Rank.PAWN)]) == MeldKind.PAWN_TRIO
    assert identify_meld([c(R, Rank.PAWN), c(G, Rank.PAWN), c(Y, Rank.PAWN), c(W, Rank.PAWN)]) == MeldKind.PAWN_QUAD
    # Hai đỏ một xanh KHÔNG hợp lệ
    assert identify_meld([c(R, Rank.PAWN, 0), c(R, Rank.PAWN, 1), c(G, Rank.PAWN)]) is None
    assert identify_meld([c(R, Rank.PAWN, 0), c(R, Rank.PAWN, 1), c(G, Rank.PAWN), c(Y, Rank.PAWN)]) is None


def test_pawn_sets_can_be_disabled_by_profile():
    rules = MeldRules(pawn_trio=False, pawn_quad=False)
    assert identify_meld([c(R, Rank.PAWN), c(G, Rank.PAWN), c(Y, Rank.PAWN)], rules) is None


def test_duplicate_card_is_not_a_meld():
    x = c(R, Rank.PAWN, 0)
    assert identify_meld([x, x]) is None


def test_meld_options_with_new_card():
    hand = [c(R, Rank.CHARIOT, 0), c(R, Rank.CHARIOT, 1), c(R, Rank.CANNON), c(R, Rank.HORSE), c(G, Rank.PAWN)]
    kinds = sorted(k.value for k, _ in meld_options_with(hand, c(R, Rank.CHARIOT, 2)))
    assert kinds == ["odd_cch", "pair", "triplet"]
    pawn_opts = meld_options_with([c(G, Rank.PAWN), c(Y, Rank.PAWN), c(W, Rank.PAWN)], c(R, Rank.PAWN))
    assert sorted(k.value for k, _ in pawn_opts) == ["pawn_quad", "pawn_trio", "pawn_trio", "pawn_trio"]


def test_trash_count_examples():
    assert trash_count([]) == 0
    assert trash_count([c(R, Rank.GENERAL)]) == 0  # Tướng lẻ không là rác
    assert trash_count([c(R, Rank.GENERAL)], MeldRules(lone_general_ok=False)) == 1
    hand = [c(R, Rank.CHARIOT), c(R, Rank.CANNON), c(R, Rank.HORSE), c(G, Rank.ADVISOR), c(Y, Rank.HORSE)]
    assert trash_count(hand) == 2
    # Tốt: Đỏ Đỏ Xanh Vàng → bộ ba màu + 1 rác (hoặc đôi đỏ + 2 rác) → tối ưu 1
    assert trash_count([c(R, Rank.PAWN, 0), c(R, Rank.PAWN, 1), c(G, Rank.PAWN), c(Y, Rank.PAWN)]) == 1


def _brute(cards, rules):
    if not cards:
        return 0
    first, rest = cards[0], cards[1:]
    best = (0 if first.rank == Rank.GENERAL and rules.lone_general_ok else 1) + _brute(rest, rules)
    from itertools import combinations

    for size in (1, 2, 3):
        for combo in combinations(range(len(rest)), size):
            group = [first] + [rest[i] for i in combo]
            kind = identify_meld(group, rules)
            if kind is None or (kind == MeldKind.PAIR and not rules.pairs_ok):
                continue
            remaining = [x for i, x in enumerate(rest) if i not in combo]
            best = min(best, _brute(remaining, rules))
    return best


@pytest.mark.parametrize("rules", [MeldRules(), MeldRules(pairs_ok=False, lone_general_ok=False)])
def test_trash_solver_matches_brute_force(rules):
    rng = random.Random(123)
    deck = build_deck()
    for _ in range(300):
        hand = rng.sample(deck, rng.randint(1, 9))
        assert trash_count(hand, rules) == _brute(hand, rules), [x.id for x in hand]


def test_analyze_partitions_every_card_once():
    rng = random.Random(5)
    deck = build_deck()
    for _ in range(50):
        hand = rng.sample(deck, 20)
        a = analyze(hand)
        used = [x.id for _, cs in a.groups for x in cs] + [x.id for x in a.trash]
        assert sorted(used) == sorted(x.id for x in hand)
        for label, cs in a.groups:
            if label != "single_general":
                assert identify_meld(cs) == MeldKind(label)
        assert a.trash_count == trash_count(hand)


def test_card_lookup():
    assert card("WHITE-HORSE-3").rank == Rank.HORSE
