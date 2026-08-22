# orderbooksim

Price-time priority limit order book. Matching is plain Python; Streamlit is just the UI.

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

## How it's put together

`matching_engine.py` does the real work and doesn't import Streamlit. `models.py` has Order/Trade/etc. `app.py` is the front end — book, charts, order form, live sim. Tests live under `tests/`.

Book state sits in `st.session_state` for the session. Refresh or hit Reset and it's gone.

Matching is price-time priority: better prices go first, and at the same price the earlier order fills first (FIFO). If an order crosses the book it walks levels until it's done or there's nothing left to hit. Partials are fine — whatever's left rests. Prints go through at the resting order's price.

Under the hood price levels are a `SortedDict` (bids via `-price`, asks ascending) and each level is a `deque` so time priority is just append / popleft.
