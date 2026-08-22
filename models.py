from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import time


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    id: int
    side: Side
    price: float
    quantity: float
    remaining_quantity: float
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        order_id: int,
        side: Side,
        price: float,
        quantity: float,
        timestamp: Optional[float] = None,
    ) -> "Order":
        ts = time.time() if timestamp is None else timestamp
        return cls(
            id=order_id,
            side=side,
            price=price,
            quantity=quantity,
            remaining_quantity=quantity,
            timestamp=ts,
        )


@dataclass
class Trade:
    id: int
    buy_order_id: int
    sell_order_id: int
    price: float
    quantity: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class PriceLevel:
    price: float
    quantity: float
    order_count: int


@dataclass
class BookSnapshot:
    bids: List[PriceLevel]
    asks: List[PriceLevel]
