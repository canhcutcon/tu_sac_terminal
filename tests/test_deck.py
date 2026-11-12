from collections import Counter

import pytest

from tusac.deck import build_deck, card, deal, shuffled_deck
from tusac.models import DECK_SIZE, SEATS, Card, Color, Rank


def test_deck_has_112_unique_ids():
    deck = build_deck()
    assert len(deck) == DECK_SIZE == 112
    assert len({c.id for c in deck}) == 112


def test_each_color_rank_appears_exactly_four_times():
    counts = Counter(c.kind for c in build_deck())
    assert len(counts) == 4 * 7
    assert set(counts.values()) == {4}


def test_card_id_round_trip():
    c = Card(Color.RED, Rank.PAWN, 0)
    assert c.id == "RED-PAWN-0"
    assert Card.from_id("RED-PAWN-0") == c
    assert card("RED-PAWN-0") is not None
    for bad in ("RED-PAWN-4", "BLUE-PAWN-0", "RED-PAWN", "", "RED-KING-1"):
        with pytest.raises(ValueError):
            Card.from_id(bad)


@pytest.mark.parametrize("dealer", SEATS)
def test_deal_sizes_and_uniqueness(dealer):
    hands, stock = deal(42, dealer)
    assert len(hands[dealer]) == 21
    assert all(len(hands[s]) == 20 for s in SEATS if s != dealer)
    assert len(stock) == 31
    all_ids = [c.id for h in hands.values() for c in h] + [c.id for c in stock]
    assert len(all_ids) == 112 == len(set(all_ids))


def test_shuffle_is_deterministic_per_seed():
    assert [c.id for c in shuffled_deck(7)] == [c.id for c in shuffled_deck(7)]
    assert [c.id for c in shuffled_deck(7)] != [c.id for c in shuffled_deck(8)]


def test_han_glyphs_follow_color_group():
    from tusac.models import han

    red_yellow = "帥仕相俥炮傌卒"
    white_green = "將士象車包馬兵"
    for color, expected in ((Color.RED, red_yellow), (Color.YELLOW, red_yellow),
                            (Color.WHITE, white_green), (Color.GREEN, white_green)):
        assert "".join(han(color, r) for r in Rank) == expected
