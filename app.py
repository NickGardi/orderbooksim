"""Streamlit UI for the limit order book."""

from __future__ import annotations

import random
import time
from datetime import datetime
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from matching_engine import MatchingEngine
from models import BookSnapshot, Order, Side, Trade


SYMBOL = "BTC/USD"
DEFAULT_MID = 50400.0
MAX_TRADE_HISTORY = 500
SIM_TICK_SECONDS = 0.45
SIM_CLOCK_STEP = 0.75


def _fmt_price(p: float) -> str:
    return f"${p:,.2f}"


def _fmt_qty(q: float) -> str:
    return f"{q:,.4f}".rstrip("0").rstrip(".")


def _init_state() -> None:
    if "engine" not in st.session_state:
        st.session_state.engine = MatchingEngine()
    if "trade_history" not in st.session_state:
        st.session_state.trade_history: List[Trade] = []
    if "live_sim" not in st.session_state:
        st.session_state.live_sim = False
    if "sim_mid" not in st.session_state:
        st.session_state.sim_mid = DEFAULT_MID
    if "sim_speed" not in st.session_state:
        st.session_state.sim_speed = 4
    if "sim_clock" not in st.session_state:
        st.session_state.sim_clock = time.time()


def _seed_book(engine: MatchingEngine, mid: float = DEFAULT_MID) -> None:
    for offset, qty in [(5, 0.8), (10, 1.2), (25, 2.0), (50, 3.5), (100, 5.0)]:
        engine.submit_order(
            Order.create(engine.next_order_id(), Side.BUY, mid - offset, qty)
        )
    for offset, qty in [(5, 0.7), (15, 1.5), (30, 2.2), (60, 4.0), (120, 6.0)]:
        engine.submit_order(
            Order.create(engine.next_order_id(), Side.SELL, mid + offset, qty)
        )


def _trim_trade_history(history: List[Trade]) -> None:
    if len(history) > MAX_TRADE_HISTORY:
        del history[:-MAX_TRADE_HISTORY]


def _sim_one_order(engine: MatchingEngine, force_side: Optional[Side] = None) -> List[Trade]:
    best_bid, best_ask = engine.get_best_bid_ask()

    if best_bid is not None and best_ask is not None:
        book_mid = (best_bid + best_ask) / 2.0
        st.session_state.sim_mid = 0.7 * book_mid + 0.3 * st.session_state.sim_mid
    mid = st.session_state.sim_mid + random.uniform(-4.0, 4.0)

    snap = engine.get_book_snapshot(depth=3)
    bids_thin = len(snap.bids) < 2
    asks_thin = len(snap.asks) < 2

    side = force_side if force_side is not None else (
        Side.BUY if random.random() < 0.5 else Side.SELL
    )
    qty = round(random.uniform(0.2, 1.5), 2)
    roll = random.random()

    if side is Side.BUY and (asks_thin or best_ask is None):
        price = round((best_bid if best_bid is not None else mid) - random.choice([5, 10, 20, 35]), 2)
    elif side is Side.SELL and (bids_thin or best_bid is None):
        price = round((best_ask if best_ask is not None else mid) + random.choice([5, 10, 20, 35]), 2)
    elif best_bid is None or best_ask is None or roll < 0.40:
        if side is Side.BUY:
            ref = best_bid if best_bid is not None else mid
            price = round(ref - random.choice([5, 10, 15, 25, 40]), 2)
        else:
            ref = best_ask if best_ask is not None else mid
            price = round(ref + random.choice([5, 10, 15, 25, 40]), 2)
    elif roll < 0.80:
        price = best_ask if side is Side.BUY else best_bid
    else:
        qty = round(random.uniform(0.8, 2.5), 2)
        if side is Side.BUY:
            price = round(best_ask + random.choice([0, 5, 10]), 2)
        else:
            price = round(best_bid - random.choice([0, 5, 10]), 2)

    order = Order.create(engine.next_order_id(), side, float(price), float(qty))
    return engine.submit_order(order)


def _rebalance_book(engine: MatchingEngine) -> None:
    snap = engine.get_book_snapshot(depth=5)
    mid = st.session_state.sim_mid
    best_bid, best_ask = engine.get_best_bid_ask()
    if best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / 2.0
        st.session_state.sim_mid = mid

    if len(snap.bids) < 3:
        for offset, qty in [(5, 1.0), (15, 1.5), (30, 2.0)]:
            engine.submit_order(
                Order.create(engine.next_order_id(), Side.BUY, round(mid - offset, 2), qty)
            )
    if len(snap.asks) < 3:
        for offset, qty in [(5, 1.0), (15, 1.5), (30, 2.0)]:
            engine.submit_order(
                Order.create(engine.next_order_id(), Side.SELL, round(mid + offset, 2), qty)
            )


def _stamp_sim_trades(trades: List[Trade]) -> None:
    for trade in trades:
        st.session_state.sim_clock += SIM_CLOCK_STEP
        trade.timestamp = st.session_state.sim_clock


def _run_sim_tick(engine: MatchingEngine, history: List[Trade]) -> None:
    speed = max(1, int(st.session_state.sim_speed))
    _rebalance_book(engine)

    for _ in range(speed):
        sides = [Side.BUY, Side.SELL]
        if random.random() < 0.5:
            sides.reverse()
        for side in sides:
            trades = _sim_one_order(engine, force_side=side)
            if trades:
                _stamp_sim_trades(trades)
                history.extend(trades)

    _trim_trade_history(history)


def _summarize_trades(trades: List[Trade]) -> str:
    parts = [f"{_fmt_qty(t.quantity)} @ {_fmt_price(t.price)}" for t in trades]
    return ", ".join(parts)


def _build_depth_chart(snap: BookSnapshot) -> go.Figure:
    fig = go.Figure()

    if snap.bids:
        bid_cum: List[float] = []
        running = 0.0
        for lvl in snap.bids:
            running += lvl.quantity
            bid_cum.append(running)
        bid_prices = [lvl.price for lvl in reversed(snap.bids)]
        bid_depth = list(reversed(bid_cum))
        fig.add_trace(
            go.Scatter(
                x=bid_prices,
                y=bid_depth,
                name="Bids",
                mode="lines",
                line=dict(color="#26a69a", width=1.5, shape="hv"),
                fill="tozeroy",
                fillcolor="rgba(38,166,154,0.28)",
                hovertemplate="Bid %{x:$,.2f}<br>Depth %{y:.4f}<extra></extra>",
            )
        )

    if snap.asks:
        ask_cum: List[float] = []
        running = 0.0
        for lvl in snap.asks:
            running += lvl.quantity
            ask_cum.append(running)
        ask_prices = [lvl.price for lvl in snap.asks]
        fig.add_trace(
            go.Scatter(
                x=ask_prices,
                y=ask_cum,
                name="Asks",
                mode="lines",
                line=dict(color="#ef5350", width=1.5, shape="hv"),
                fill="tozeroy",
                fillcolor="rgba(239,83,80,0.28)",
                hovertemplate="Ask %{x:$,.2f}<br>Depth %{y:.4f}<extra></extra>",
            )
        )

    if not snap.bids and not snap.asks:
        fig.add_annotation(
            text="Empty book",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color="#848e9c", size=14),
        )

    fig.update_layout(
        title=dict(text=f"{SYMBOL} · market depth", font=dict(color="#d1d4dc", size=16)),
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        height=280,
        margin=dict(l=50, r=20, t=50, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        font=dict(color="#d1d4dc"),
        xaxis=dict(title="Price", gridcolor="#1e222d", tickprefix="$", tickformat=",.2f"),
        yaxis=dict(title="Cumulative size", gridcolor="#1e222d", fixedrange=True),
    )
    return fig


def _trades_to_ohlcv(history: List[Trade], bucket_seconds: float = 2.0) -> pd.DataFrame:
    rows = [
        {
            "time": datetime.fromtimestamp(t.timestamp),
            "price": t.price,
            "quantity": t.quantity,
        }
        for t in history
    ]
    df = pd.DataFrame(rows)
    df = df.set_index("time").sort_index()
    rule = f"{max(int(bucket_seconds), 1)}s"
    ohlc = df["price"].resample(rule).ohlc()
    vol = df["quantity"].resample(rule).sum().rename("volume")
    return ohlc.join(vol).dropna(subset=["open"])


def _build_price_chart(
    history: List[Trade],
    best_bid: Optional[float],
    best_ask: Optional[float],
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.02,
        row_heights=[0.88, 0.12],
    )

    price_lo: Optional[float] = None
    price_hi: Optional[float] = None

    if history:
        candles = _trades_to_ohlcv(history)
        fig.add_trace(
            go.Candlestick(
                x=candles.index,
                open=candles["open"],
                high=candles["high"],
                low=candles["low"],
                close=candles["close"],
                name="OHLC",
                increasing_line_color="#26a69a",
                increasing_fillcolor="#26a69a",
                decreasing_line_color="#ef5350",
                decreasing_fillcolor="#ef5350",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
        times = [datetime.fromtimestamp(t.timestamp) for t in history]
        prices = [t.price for t in history]
        fig.add_trace(
            go.Scatter(
                x=times,
                y=prices,
                mode="lines",
                name="Last",
                line=dict(color="#f0b90b", width=1.2),
                hovertemplate="%{x|%H:%M:%S}<br>$%{y:,.2f}<extra>Last</extra>",
            ),
            row=1,
            col=1,
        )
        colors = [
            "rgba(38,166,154,0.45)" if row.close >= row.open else "rgba(239,83,80,0.45)"
            for row in candles.itertuples()
        ]
        fig.add_trace(
            go.Bar(
                x=candles.index,
                y=candles["volume"],
                name="Volume",
                marker=dict(color=colors, line=dict(width=0)),
                showlegend=False,
                hovertemplate="%{y:.4f}<extra>Vol</extra>",
            ),
            row=2,
            col=1,
        )
        price_lo = float(min(candles["low"].min(), min(prices)))
        price_hi = float(max(candles["high"].max(), max(prices)))
    else:
        fig.add_trace(
            go.Scatter(x=[], y=[], mode="lines", name="Last", line=dict(color="#f0b90b")),
            row=1,
            col=1,
        )
        fig.add_annotation(
            text="No trades yet",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color="#848e9c", size=14),
            row=1,
            col=1,
        )

    if price_lo is not None and price_hi is not None:
        pad = max((price_hi - price_lo) * 0.08, 5.0)
        y_min, y_max = price_lo - pad, price_hi + pad
        for price, label, color in (
            (best_bid, "Bid", "#26a69a"),
            (best_ask, "Ask", "#ef5350"),
        ):
            if price is not None and y_min <= price <= y_max:
                fig.add_hline(
                    y=price,
                    line_dash="dot",
                    line_color=color,
                    line_width=1,
                    annotation_text=f"{label} {_fmt_price(price)}",
                    annotation_position="top left",
                    annotation_font_color=color,
                    annotation_font_size=11,
                    row=1,
                    col=1,
                )
        fig.update_yaxes(range=[y_min, y_max], row=1, col=1)

    fig.update_layout(
        title=dict(text=f"{SYMBOL} · last price", font=dict(color="#d1d4dc", size=16)),
        template="plotly_dark",
        paper_bgcolor="#131722",
        plot_bgcolor="#131722",
        height=480,
        margin=dict(l=50, r=20, t=50, b=30),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        hovermode="x unified",
        font=dict(color="#d1d4dc"),
        bargap=0.35,
    )
    fig.update_xaxes(gridcolor="#1e222d", showgrid=True, zeroline=False)
    fig.update_yaxes(
        title_text="",
        gridcolor="#1e222d",
        tickprefix="$",
        tickformat=",.2f",
        row=1,
        col=1,
    )
    fig.update_yaxes(
        title_text="",
        gridcolor="#1e222d",
        showticklabels=False,
        fixedrange=True,
        row=2,
        col=1,
    )
    fig.update_xaxes(rangeslider_visible=False)
    return fig


def main() -> None:
    st.set_page_config(
        page_title="Limit Order Book Simulator",
        layout="wide",
    )
    _init_state()
    engine: MatchingEngine = st.session_state.engine

    with st.sidebar:
        st.header("Controls")
        if st.button("Seed book", use_container_width=True, disabled=st.session_state.live_sim):
            if engine.get_best_bid_ask() == (None, None) and not engine.all_trades():
                _seed_book(engine, st.session_state.sim_mid)
                st.success("Book seeded.")
            else:
                st.warning("Reset the book before seeding.")
            st.rerun()

        st.subheader("Live market")
        st.slider(
            "Sim speed",
            min_value=1,
            max_value=10,
            step=1,
            key="sim_speed",
        )
        c_start, c_stop = st.columns(2)
        with c_start:
            if st.button(
                "Start live",
                use_container_width=True,
                disabled=st.session_state.live_sim,
                type="primary",
            ):
                bid, ask = engine.get_best_bid_ask()
                if bid is None and ask is None:
                    _seed_book(engine, st.session_state.sim_mid)
                st.session_state.sim_clock = time.time()
                st.session_state.live_sim = True
                st.rerun()
        with c_stop:
            if st.button(
                "Stop",
                use_container_width=True,
                disabled=not st.session_state.live_sim,
            ):
                st.session_state.live_sim = False
                st.rerun()

        if st.session_state.live_sim:
            st.success(f"Live · {int(st.session_state.sim_speed)}x")
        else:
            st.caption("Stopped")

        if st.button("Reset book", use_container_width=True):
            st.session_state.live_sim = False
            engine.reset()
            st.session_state.trade_history = []
            st.session_state.sim_mid = DEFAULT_MID
            st.session_state.sim_clock = time.time()
            st.rerun()

    st.title(f"Limit Order Book — {SYMBOL}")

    best_bid, best_ask = engine.get_best_bid_ask()
    spread = engine.get_spread()
    history: List[Trade] = st.session_state.trade_history
    last_px = history[-1].price if history else None
    ops = engine.orders_per_second(1.0)
    tps = engine.trades_per_second(1.0)

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Best Bid", _fmt_price(best_bid) if best_bid is not None else "—")
    m2.metric("Best Ask", _fmt_price(best_ask) if best_ask is not None else "—")
    m3.metric("Spread", _fmt_price(spread) if spread is not None else "—")
    m4.metric("Last", _fmt_price(last_px) if last_px is not None else "—")
    m5.metric("Orders/sec", f"{ops:.1f}")
    m6.metric("Trades/sec", f"{tps:.1f}")

    st.plotly_chart(
        _build_price_chart(history, best_bid, best_ask),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    snap = engine.get_book_snapshot(depth=25)
    st.plotly_chart(
        _build_depth_chart(snap),
        use_container_width=True,
        config={"displayModeBar": False},
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Bids (buy)")
        if snap.bids:
            bid_df = pd.DataFrame(
                {
                    "Price": [lvl.price for lvl in snap.bids],
                    "Quantity": [lvl.quantity for lvl in snap.bids],
                    "Orders": [lvl.order_count for lvl in snap.bids],
                }
            )
            bid_df["Price"] = bid_df["Price"].map(_fmt_price)
            bid_df["Quantity"] = bid_df["Quantity"].map(_fmt_qty)
            st.dataframe(bid_df, use_container_width=True, hide_index=True)
        else:
            st.info("No bids")

    with right:
        st.subheader("Asks (sell)")
        if snap.asks:
            ask_df = pd.DataFrame(
                {
                    "Price": [lvl.price for lvl in snap.asks],
                    "Quantity": [lvl.quantity for lvl in snap.asks],
                    "Orders": [lvl.order_count for lvl in snap.asks],
                }
            )
            ask_df["Price"] = ask_df["Price"].map(_fmt_price)
            ask_df["Quantity"] = ask_df["Quantity"].map(_fmt_qty)
            st.dataframe(ask_df, use_container_width=True, hide_index=True)
        else:
            st.info("No asks")

    st.subheader("Submit order")
    with st.form("order_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            side_label = st.radio("Side", ["Buy", "Sell"], horizontal=True)
        with c2:
            default_price = best_ask if best_ask is not None else (
                best_bid if best_bid is not None else float(st.session_state.sim_mid)
            )
            price = st.number_input(
                "Price",
                min_value=0.01,
                value=float(default_price),
                step=0.5,
                format="%.2f",
            )
        with c3:
            quantity = st.number_input(
                "Quantity",
                min_value=0.0001,
                value=1.0,
                step=0.1,
                format="%.4f",
            )
        submitted = st.form_submit_button(
            "Submit",
            use_container_width=True,
            disabled=st.session_state.live_sim,
        )

    if submitted and not st.session_state.live_sim:
        if price <= 0:
            st.error("Price must be positive.")
        elif quantity <= 0:
            st.error("Quantity must be positive.")
        else:
            side = Side.BUY if side_label == "Buy" else Side.SELL
            order = Order.create(engine.next_order_id(), side, float(price), float(quantity))
            try:
                trades = engine.submit_order(order)
            except ValueError as exc:
                st.error(str(exc))
            else:
                if trades:
                    st.session_state.trade_history.extend(trades)
                    _trim_trade_history(st.session_state.trade_history)
                    st.success(f"Matched: {_summarize_trades(trades)}")
                else:
                    st.info(
                        f"Order rested in the book — "
                        f"{side_label} {_fmt_qty(quantity)} @ {_fmt_price(price)}"
                    )
                st.rerun()

    st.subheader("Recent trades")
    recent = list(reversed(history[-15:]))
    if recent:
        trade_df = pd.DataFrame(
            {
                "Time": [
                    datetime.fromtimestamp(t.timestamp).strftime("%H:%M:%S")
                    for t in recent
                ],
                "Price": [_fmt_price(t.price) for t in recent],
                "Quantity": [_fmt_qty(t.quantity) for t in recent],
                "Buy #": [t.buy_order_id for t in recent],
                "Sell #": [t.sell_order_id for t in recent],
            }
        )
        st.dataframe(trade_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No trades yet.")

    if st.session_state.live_sim:
        speed = max(1, int(st.session_state.sim_speed))
        time.sleep(max(0.05, SIM_TICK_SECONDS / speed))
        _run_sim_tick(engine, st.session_state.trade_history)
        st.rerun()


if __name__ == "__main__":
    main()
