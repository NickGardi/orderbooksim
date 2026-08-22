# orderbooksim

Price-time priority limit order book. Matching engine is plain Python; Streamlit is just the UI.

Live: https://nickgardi-orderbooksim-app-m4vk2z.streamlit.app/

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

```bash
pytest
```

## Architecture

| File | What it does |
|------|----------------|
| `matching_engine.py` | Core matcher — no Streamlit imports |
| `models.py` | `Order`, `Trade`, `Side`, book snapshot types |
| `app.py` | Streamlit UI (book, charts, order form, live sim) |
| `tests/` | Engine tests (crossing, partials, FIFO, cancel, empty book) |

The UI keeps an engine instance in `st.session_state`. Nothing is persisted — refresh or **Reset** clears it.

### Matching

- **Price priority:** best bid = highest price, best ask = lowest price
- **Time priority:** at the same price, earlier orders fill first (FIFO)
- Incoming orders that cross the book walk levels until filled or no more liquidity
- Partial fills are allowed; leftover quantity rests on the book
- Trade price is the resting (maker) order’s limit

### Data structures

- `SortedDict` for price levels (bids keyed by `-price`, asks ascending)
- `deque` per level so append = new order, popleft = oldest fill
- Order id → (side, price) index for cancels

That’s the usual continuous limit-order-book model exchanges use for limit orders.
