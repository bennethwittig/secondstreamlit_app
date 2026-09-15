"""
Watchlist Explorer — Step 7 version: real prices behind an API key.

Needs .streamlit/secrets.toml containing:
    ALPHAVANTAGE_API_KEY = "your-key"

Free key (instant, no card): alphavantage.co/support/#api-key
Free tier: 25 requests/day, 5/minute — one request per ticker, so keep the list short.

Run it with:   streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(page_title="Watchlist Explorer", layout="wide")
st.title("Watchlist Explorer")
st.caption("Live daily closing prices from Alpha Vantage.")


# --- 1. cache the expensive load -------------------------------------------
@st.cache_data(ttl=3600)
def load_prices(symbol):
    """One request per symbol. Cached for an hour so we don't burn the daily quota."""
    r = requests.get(
        "https://www.alphavantage.co/query",
        params={
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "apikey": st.secrets["ALPHAVANTAGE_API_KEY"],
            "outputsize": "compact",
        },
        timeout=10,
    )
    payload = r.json()

    series = payload.get("Time Series (Daily)")
    if series is None:
        # the API answers 200 OK even when it refuses — read the payload, not the status
        raise RuntimeError(
            payload.get("Information") or payload.get("Note") or
            payload.get("Error Message") or "Unexpected response from Alpha Vantage"
        )

    out = (
        pd.DataFrame(series).T
        .rename(columns={"4. close": "price"})[["price"]]
        .astype(float)
        .rename_axis("date")
        .reset_index()
    )
    out["date"] = pd.to_datetime(out["date"])
    out["ticker"] = symbol
    return out.sort_values("date")


@st.cache_data(ttl=3600)
def load_data(symbols):
    return pd.concat([load_prices(s) for s in symbols], ignore_index=True)


# --- 2. sidebar: tickers + slider + checkbox --------------------------------
with st.sidebar:
    st.header("Controls")
    raw = st.text_input("Tickers (comma separated)", value="AAPL,MSFT,IBM")
    tickers = [t.strip().upper() for t in raw.split(",") if t.strip()]
    st.caption("One API request per ticker · 25 per day on the free tier")

if not tickers:
    st.info("Type at least one ticker in the sidebar.")
    st.stop()

try:
    df = load_data(tuple(tickers))
except RuntimeError as err:
    st.error(f"Alpha Vantage said: {err}")
    st.caption("Out of requests for today, or the key is wrong. Check .streamlit/secrets.toml.")
    st.stop()

with st.sidebar:
    start, end = st.slider(
        "Date range",
        min_value=df["date"].min().date(),
        max_value=df["date"].max().date(),
        value=(df["date"].min().date(), df["date"].max().date()),
    )
    rebase = st.checkbox("Rebase to 100 at window start", value=True)

view = df[df["date"].dt.date.between(start, end)].copy()

if view.empty:
    st.info("No data in that window.")
    st.stop()

if rebase:
    view["price"] = view.groupby("ticker")["price"].transform(lambda s: s / s.iloc[0] * 100)

# --- 3. headline numbers + a chart that reacts ------------------------------
perf = view.groupby("ticker")["price"].agg(["first", "last"])
perf["return_%"] = (perf["last"] / perf["first"] - 1) * 100
best = perf["return_%"].idxmax()

c1, c2, c3 = st.columns(3)
c1.metric("Tickers", len(tickers))
c2.metric("Trading days", view["date"].nunique())
c3.metric(f"Best: {best}", f"{perf.loc[best, 'return_%']:+.1f}%")

fig = px.line(
    view,
    x="date",
    y="price",
    color="ticker",
    labels={"price": "Rebased (start = 100)" if rebase else "Closing price", "date": ""},
)
fig.update_layout(height=420, margin=dict(t=10, b=0), legend_title_text="")
st.plotly_chart(fig)

# --- 4. session_state: pinned views survive reruns --------------------------
if "pinned" not in st.session_state:
    st.session_state.pinned = []

left, right, _ = st.columns([1, 1, 4])
if left.button("Pin this view"):
    st.session_state.pinned.append(
        {
            "tickers": ", ".join(tickers),
            "from": start,
            "to": end,
            "best": best,
            "return_%": round(float(perf.loc[best, "return_%"]), 1),
        }
    )
if right.button("Clear pins"):
    st.session_state.pinned = []

if st.session_state.pinned:
    st.subheader("Pinned views")
    pins = pd.DataFrame(st.session_state.pinned)
    st.dataframe(pins, hide_index=True)
    st.download_button(
        "Download pinned views (CSV)",
        data=pins.to_csv(index=False).encode("utf-8"),
        file_name="pinned_views.csv",
        mime="text/csv",
    )

# --- 5. let the stakeholder take the data home ------------------------------
st.download_button(
    "Download filtered data (CSV)",
    data=view.to_csv(index=False).encode("utf-8"),
    file_name="watchlist.csv",
    mime="text/csv",
)
