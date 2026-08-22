from __future__ import annotations

from typing import Optional

import pytest

from matching_engine import MatchingEngine
from models import Order, Side


def make_order(
    engine: MatchingEngine,
    side: Side,
    price: float,
    quantity: float,
    order_id: Optional[int] = None,
) -> Order:
    oid = engine.next_order_id() if order_id is None else order_id
    return Order.create(oid, side, price, quantity)


class TestRestingNonCrossing:
    def test_limit_that_does_not_cross_rests_unmatched(self):
        eng = MatchingEngine()
        eng.submit_order(make_order(eng, Side.BUY, 100.0, 1.0))
        trades = eng.submit_order(make_order(eng, Side.SELL, 101.0, 1.0))

        assert trades == []
        bid, ask = eng.get_best_bid_ask()
        assert bid == 100.0
        assert ask == 101.0
        snap = eng.get_book_snapshot()
        assert len(snap.bids) == 1 and snap.bids[0].quantity == 1.0
        assert len(snap.asks) == 1 and snap.asks[0].quantity == 1.0


class TestExactCross:
    def test_exact_cross_fully_fills_both_sides(self):
        eng = MatchingEngine()
        buy = make_order(eng, Side.BUY, 100.0, 1.0)
        eng.submit_order(buy)

        sell = make_order(eng, Side.SELL, 100.0, 1.0)
        trades = eng.submit_order(sell)

        assert len(trades) == 1
        t = trades[0]
        assert t.price == 100.0
        assert t.quantity == 1.0
        assert t.buy_order_id == buy.id
        assert t.sell_order_id == sell.id
        assert buy.remaining_quantity == 0
        assert sell.remaining_quantity == 0

        bid, ask = eng.get_best_bid_ask()
        assert bid is None and ask is None


class TestPartialFill:
    def test_partial_fill_remainder_rests(self):
        eng = MatchingEngine()
        resting = make_order(eng, Side.SELL, 50.0, 1.0)
        eng.submit_order(resting)

        aggressive = make_order(eng, Side.BUY, 50.0, 2.5)
        trades = eng.submit_order(aggressive)

        assert len(trades) == 1
        assert trades[0].quantity == 1.0
        assert resting.remaining_quantity == 0
        assert aggressive.remaining_quantity == 1.5

        bid, ask = eng.get_best_bid_ask()
        assert bid == 50.0
        assert ask is None
        assert eng.get_book_snapshot().bids[0].quantity == 1.5


class TestMultiLevelWalk:
    def test_walks_multiple_price_levels(self):
        eng = MatchingEngine()
        # Three ask levels
        o1 = make_order(eng, Side.SELL, 100.0, 1.0)
        o2 = make_order(eng, Side.SELL, 101.0, 1.0)
        o3 = make_order(eng, Side.SELL, 102.0, 1.0)
        for o in (o1, o2, o3):
            eng.submit_order(o)

        # Buy large enough to clear first two levels and partially third
        buy = make_order(eng, Side.BUY, 102.0, 2.5)
        trades = eng.submit_order(buy)

        assert len(trades) == 3
        assert [t.price for t in trades] == [100.0, 101.0, 102.0]
        assert [t.quantity for t in trades] == [1.0, 1.0, 0.5]
        assert buy.remaining_quantity == 0

        bid, ask = eng.get_best_bid_ask()
        assert bid is None
        assert ask == 102.0
        snap = eng.get_book_snapshot()
        assert snap.asks[0].quantity == pytest.approx(0.5)


class TestPriceTimePriority:
    def test_earlier_order_at_same_price_fills_first(self):
        eng = MatchingEngine()
        first = make_order(eng, Side.BUY, 100.0, 1.0)
        second = make_order(eng, Side.BUY, 100.0, 1.0)
        eng.submit_order(first)
        eng.submit_order(second)

        sell = make_order(eng, Side.SELL, 100.0, 1.0)
        trades = eng.submit_order(sell)

        assert len(trades) == 1
        assert trades[0].buy_order_id == first.id
        assert first.remaining_quantity == 0
        assert second.remaining_quantity == 1.0

        # Second should still be alone at 100
        snap = eng.get_book_snapshot()
        assert len(snap.bids) == 1
        assert snap.bids[0].order_count == 1
        assert eng.get_order(second.id) is not None
        assert eng.get_order(first.id) is None


class TestCancel:
    def test_cancel_removes_correct_order(self):
        eng = MatchingEngine()
        keep = make_order(eng, Side.BUY, 99.0, 1.0)
        kill = make_order(eng, Side.BUY, 100.0, 2.0)
        other = make_order(eng, Side.SELL, 105.0, 1.0)
        eng.submit_order(keep)
        eng.submit_order(kill)
        eng.submit_order(other)

        assert eng.cancel_order(kill.id) is True
        assert eng.get_order(kill.id) is None
        assert eng.get_order(keep.id) is not None
        assert eng.get_order(other.id) is not None

        bid, ask = eng.get_best_bid_ask()
        assert bid == 99.0
        assert ask == 105.0

    def test_cancel_nonexistent_returns_false(self):
        eng = MatchingEngine()
        assert eng.cancel_order(999) is False


class TestEmptyBook:
    def test_submit_into_empty_book_rests(self):
        eng = MatchingEngine()
        trades = eng.submit_order(make_order(eng, Side.BUY, 42.0, 3.0))
        assert trades == []
        bid, ask = eng.get_best_bid_ask()
        assert bid == 42.0
        assert ask is None

    def test_sell_into_empty_book_rests(self):
        eng = MatchingEngine()
        trades = eng.submit_order(make_order(eng, Side.SELL, 42.0, 3.0))
        assert trades == []
        bid, ask = eng.get_best_bid_ask()
        assert bid is None
        assert ask == 42.0


class TestValidation:
    def test_rejects_non_positive_quantity(self):
        eng = MatchingEngine()
        with pytest.raises(ValueError):
            eng.submit_order(make_order(eng, Side.BUY, 10.0, 0.0))

    def test_rejects_non_positive_price(self):
        eng = MatchingEngine()
        with pytest.raises(ValueError):
            eng.submit_order(make_order(eng, Side.BUY, 0.0, 1.0))


class TestSnapshotOrdering:
    def test_bids_highest_first_asks_lowest_first(self):
        eng = MatchingEngine()
        eng.submit_order(make_order(eng, Side.BUY, 98.0, 1.0))
        eng.submit_order(make_order(eng, Side.BUY, 100.0, 1.0))
        eng.submit_order(make_order(eng, Side.BUY, 99.0, 1.0))
        eng.submit_order(make_order(eng, Side.SELL, 103.0, 1.0))
        eng.submit_order(make_order(eng, Side.SELL, 101.0, 1.0))
        eng.submit_order(make_order(eng, Side.SELL, 102.0, 1.0))

        snap = eng.get_book_snapshot()
        assert [l.price for l in snap.bids] == [100.0, 99.0, 98.0]
        assert [l.price for l in snap.asks] == [101.0, 102.0, 103.0]
