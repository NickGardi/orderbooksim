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

## Code

- `matching_engine.py` — submit / cancel / snapshot. Bids sorted high→low, asks low→high, FIFO within a price (`SortedDict` + `deque`). Fills at the resting order's price.
- `models.py` — Order, Trade, etc.
- `app.py` — charts, book view, manual orders, live sim
- `tests/` — matching edge cases

State lives in memory for the session. Sidebar has seed / live / reset.
