import yfinance as yf
from datetime import datetime

candidates = [
    "^NIFTY6535",
    "^NIFTY6535.NS",
    "NIFTY6535.NS",
    "NIFTY 50 HYBRID COMPOSITE DEBT 65:35 INDEX.NS"
]

for sym in candidates:
    print(f"Testing yfinance for {sym}")
    try:
        data = yf.download(sym, start="2020-01-01", end="2020-01-10", progress=False)
        if data is not None and not data.empty:
            print(f"SUCCESS: {sym}")
            print(data.head())
        else:
            print(f"Empty for {sym}")
    except Exception as e:
        print(f"Error for {sym}: {e}")
