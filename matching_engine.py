"""Price-time priority limit order book."""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from sortedcontainers import SortedDict

from models import BookSnapshot, Order, PriceLevel, Side, Trade


class MatchingEngine:
    def __init__(self) -> None:
        # Best bid first via -price key; asks ascending.
        self._bids: SortedDict = SortedDict(lambda p: -p)
        self._asks: SortedDict = SortedDict()
        self._order_index: Dict[int, Tuple[Side, float]] = {}
        self._next_order_id: int = 1
        self._next_trade_id: int = 1
        self._trades: List[Trade] = []
        self._submit_times: Deque[float] = deque()
        self._trade_times: Deque[float] = deque()
        self._total_orders: int = 0
        self._total_trades: int = 0

    def next_order_id(self) -> int:
        oid = self._next_order_id
        self._next_order_id += 1
        return oid

    def submit_order(self, order: Order) -> List[Trade]:
        """Match against the book; rest any unfilled quantity. Returns fills."""
        if order.quantity <= 0 or order.remaining_quantity <= 0:
            raise ValueError("Order quantity must be positive")
        if order.price <= 0:
            raise ValueError("Order price must be positive")

        if order.id >= self._next_order_id:
            self._next_order_id = order.id + 1

        if order.side is Side.BUY:
            generated = self._match_buy(order)
        else:
            generated = self._match_sell(order)

        if order.remaining_quantity > 0:
            self._rest_order(order)

        now = time.time()
        self._submit_times.append(now)
        self._total_orders += 1
        for _ in generated:
            self._trade_times.append(now)
        self._total_trades += len(generated)
        self._trades.extend(generated)
        return generated

    def cancel_order(self, order_id: int) -> bool:
        loc = self._order_index.pop(order_id, None)
        if loc is None:
            return False

        side, price = loc
        book = self._bids if side is Side.BUY else self._asks
        level: Optional[Deque[Order]] = book.get(price)
        if level is None:
            return False

        for i, resting in enumerate(level):
            if resting.id == order_id:
                del level[i]
                break
        else:
            return False

        if not level:
            del book[price]
        return True

    def get_book_snapshot(self, depth: int = 10) -> BookSnapshot:
        bids = [
            PriceLevel(
                price=price,
                quantity=sum(o.remaining_quantity for o in level),
                order_count=len(level),
            )
            for price, level in list(self._bids.items())[:depth]
        ]
        asks = [
            PriceLevel(
                price=price,
                quantity=sum(o.remaining_quantity for o in level),
                order_count=len(level),
            )
            for price, level in list(self._asks.items())[:depth]
        ]
        return BookSnapshot(bids=bids, asks=asks)

    def get_best_bid_ask(self) -> Tuple[Optional[float], Optional[float]]:
        best_bid = next(iter(self._bids.keys()), None)
        best_ask = next(iter(self._asks.keys()), None)
        return best_bid, best_ask

    def get_spread(self) -> Optional[float]:
        bid, ask = self.get_best_bid_ask()
        if bid is None or ask is None:
            return None
        return ask - bid

    def get_order(self, order_id: int) -> Optional[Order]:
        loc = self._order_index.get(order_id)
        if loc is None:
            return None
        side, price = loc
        book = self._bids if side is Side.BUY else self._asks
        level = book.get(price)
        if level is None:
            return None
        for o in level:
            if o.id == order_id:
                return o
        return None

    def all_trades(self) -> List[Trade]:
        return list(self._trades)

    def orders_per_second(self, window_seconds: float = 1.0) -> float:
        return self._rate(self._submit_times, window_seconds)

    def trades_per_second(self, window_seconds: float = 1.0) -> float:
        return self._rate(self._trade_times, window_seconds)

    def throughput_stats(self, window_seconds: float = 1.0) -> Dict[str, float]:
        return {
            "orders_per_second": self.orders_per_second(window_seconds),
            "trades_per_second": self.trades_per_second(window_seconds),
            "total_orders": float(self._total_orders),
            "total_trades": float(self._total_trades),
        }

    def reset(self) -> None:
        self._bids.clear()
        self._asks.clear()
        self._order_index.clear()
        self._trades.clear()
        self._submit_times.clear()
        self._trade_times.clear()
        self._total_orders = 0
        self._total_trades = 0

    @staticmethod
    def _rate(timestamps: Deque[float], window_seconds: float) -> float:
        if window_seconds <= 0:
            return 0.0
        cutoff = time.time() - window_seconds
        while timestamps and timestamps[0] < cutoff:
            timestamps.popleft()
        return len(timestamps) / window_seconds

    def _match_buy(self, order: Order) -> List[Trade]:
        trades: List[Trade] = []
        while order.remaining_quantity > 0 and self._asks:
            best_ask_price = next(iter(self._asks.keys()))
            if order.price < best_ask_price:
                break
            level: Deque[Order] = self._asks[best_ask_price]
            trades.extend(self._fill_level(order, level, maker_is_sell=True))
            if not level:
                del self._asks[best_ask_price]
        return trades

    def _match_sell(self, order: Order) -> List[Trade]:
        trades: List[Trade] = []
        while order.remaining_quantity > 0 and self._bids:
            best_bid_price = next(iter(self._bids.keys()))
            if order.price > best_bid_price:
                break
            level: Deque[Order] = self._bids[best_bid_price]
            trades.extend(self._fill_level(order, level, maker_is_sell=False))
            if not level:
                del self._bids[best_bid_price]
        return trades

    def _fill_level(
        self,
        taker: Order,
        level: Deque[Order],
        maker_is_sell: bool,
    ) -> List[Trade]:
        trades: List[Trade] = []
        while order_has_qty(taker) and level:
            maker = level[0]
            fill_qty = min(taker.remaining_quantity, maker.remaining_quantity)
            trade_price = maker.price

            if maker_is_sell:
                buy_id, sell_id = taker.id, maker.id
            else:
                buy_id, sell_id = maker.id, taker.id

            trades.append(
                Trade(
                    id=self._alloc_trade_id(),
                    buy_order_id=buy_id,
                    sell_order_id=sell_id,
                    price=trade_price,
                    quantity=fill_qty,
                )
            )

            taker.remaining_quantity -= fill_qty
            maker.remaining_quantity -= fill_qty
            if maker.remaining_quantity <= 0:
                level.popleft()
                self._order_index.pop(maker.id, None)

        return trades

    def _rest_order(self, order: Order) -> None:
        book = self._bids if order.side is Side.BUY else self._asks
        if order.price not in book:
            book[order.price] = deque()
        book[order.price].append(order)
        self._order_index[order.id] = (order.side, order.price)

    def _alloc_trade_id(self) -> int:
        tid = self._next_trade_id
        self._next_trade_id += 1
        return tid


def order_has_qty(order: Order) -> bool:
    return order.remaining_quantity > 0
