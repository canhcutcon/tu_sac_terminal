"""Bộ bài 112 quân, xáo theo seed và chia 21/20/20/20 + nọc 31."""
from __future__ import annotations

import random
from collections.abc import Iterable

from .models import (
    COPIES,
    DEALER_HAND,
    DECK_SIZE,
    OTHER_HAND,
    SEATS,
    STOCK_SIZE,
    Card,
    Color,
    Rank,
    next_seat,
)


def build_deck() -> list[Card]:
    """4 màu × 7 loại × 4 bản sao, thứ tự cố định."""
    deck = [Card(color, rank, i) for color in Color for rank in Rank for i in range(COPIES)]
    assert len(deck) == DECK_SIZE
    return deck


CARDS: dict[str, Card] = {c.id: c for c in build_deck()}


def card(card_id: str) -> Card:
    try:
        return CARDS[card_id]
    except KeyError:
        raise ValueError(f"Không có quân với ID {card_id!r}") from None


def cards(ids: Iterable[str]) -> list[Card]:
    return [card(i) for i in ids]


def sort_ids(ids: Iterable[str]) -> list[str]:
    return sorted(ids, key=lambda i: CARDS[i])


def shuffled_deck(seed: int) -> list[Card]:
    deck = build_deck()
    random.Random(seed).shuffle(deck)
    return deck


def deal(seed: int, dealer: str) -> tuple[dict[str, list[Card]], list[Card]]:
    """Chia theo thứ tự chỗ ngồi bắt đầu từ nhà cái: cái 21, ba nhà còn lại 20, nọc 31."""
    deck = shuffled_deck(seed)
    hands: dict[str, list[Card]] = {}
    pos = 0
    for k in range(len(SEATS)):
        seat = next_seat(dealer, k)
        size = DEALER_HAND if k == 0 else OTHER_HAND
        hands[seat] = deck[pos : pos + size]
        pos += size
    stock = deck[pos:]
    if len(stock) != STOCK_SIZE:
        raise AssertionError(f"Nọc phải có {STOCK_SIZE} quân, đang có {len(stock)}")
    return {s: hands[s] for s in SEATS}, stock
