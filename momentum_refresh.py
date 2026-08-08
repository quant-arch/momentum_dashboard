import os
import time
import logging
import numpy as np
import pandas as pd
import json
from pathlib import Path
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

try:
    from truedata import TDhist
    TRUEDATA_AVAILABLE = True
except ImportError:
    TRUEDATA_AVAILABLE = False

# ─── CONFIG ───────────────────────────────────────────────────────────────────
UNIVERSE_FILE   = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Universe\ticker_master_may26.xlsx"
SECTOR_FILE     = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\ind_nifty500list_7MAY2026.csv"
OUTPUT_CSV      = "latest_momentum_scores.csv"
OUTPUT_JSON     = "latest_snapshot.json"
TD_USERNAME     = os.getenv("TRUEDATA_USERNAME")
TD_PASSWORD     = os.getenv("TRUEDATA_PASSWORD")
TD_DURATION     = "1 Y"
TD_BARSIZE      = "EOD"
TD_SLEEP        = 0.1
LOOKBACK_MONTHS = 6

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ─── DATA FETCH ───────────────────────────────────────────────────────────────

def fetch_truedata(username, password, ticker_list):
    tdhist = TDhist(username, password)
    df_list, error_list = [], []
    for ticker in ticker_list:
        try:
            df = tdhist.get_historic_data(ticker, duration=TD_DURATION, bar_size=TD_BARSIZE)
            df["Ticker"] = ticker
            df = df.rename(columns={"timestamp": "Date", "close": "Close"})
            df_list.append(df[["Date", "Close", "Ticker"]])
            logging.info(f"Fetched {ticker}: {len(df)} rows")
            time.sleep(TD_SLEEP)
        except Exception as e:
            logging.error(f"Failed {ticker}: {e}")
            error_list.append(ticker)
    return pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame(), error_list


def fetch_yfinance(ticker_list, start_date, end_date):
    import yfinance as yf
    tickers = [t + ".NS" for t in ticker_list]
    logging.info(f"Downloading {len(tickers)} symbols via yfinance from {start_date} to {end_date}")
    data = yf.download(tickers, start=str(start_date), end=str(end_date),
                       auto_adjust=True, progress=True)
    close = data["Close"] if "Close" in data.columns else data.xs("Close", axis=1, level=0)
    close.columns = [c.replace(".NS", "").upper() for c in close.columns]
    rows = []
    for sym in close.columns:
        s = close[sym].dropna().reset_index()
        s.columns = ["Date", "Close"]
        s["Ticker"] = sym
        rows.append(s)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(), []


# ─── UNIVERSE LOADER ─────────────────────────────────────────────────────────

def load_universe():
    # Read all columns — no usecols restriction
    if UNIVERSE_FILE.endswith(".csv"):
        meta = pd.read_csv(UNIVERSE_FILE)
    else:
        meta = pd.read_excel(UNIVERSE_FILE)
    meta.columns = [c.strip() for c in meta.columns]

    # Auto-detect Symbol column
    sym_col = next((c for c in ["Symbol", "Ticker", "SYMBOL", "TICKER", "symbol", "ticker"]
                    if c in meta.columns), None)
    if not sym_col:
        raise ValueError(f"No Symbol/Ticker column found in universe file. Found: {list(meta.columns)}")
    meta["Ticker"] = meta[sym_col].astype(str).str.strip().str.upper()

    # Auto-detect Company Name column
    comp_col = next((c for c in ["Company Name", "CompanyName", "Company", "NAME", "Name", "name"]
                     if c in meta.columns), None)
    meta["Company Name"] = meta[comp_col].astype(str).str.strip() if comp_col else meta["Ticker"]

    # Auto-detect Industry/Sector column
    ind_col = next((c for c in ["Industry", "Sector", "SECTOR", "INDUSTRY", "sector", "industry"]
                    if c in meta.columns), None)
    meta["Industry"] = meta[ind_col].astype(str).str.strip() if ind_col else "Unclassified"

    # Auto-detect ISIN column
    isin_col = next((c for c in ["ISIN Code", "ISIN", "isin", "isin_code", "ISIN_CODE"]
                     if c in meta.columns), None)
    meta["ISIN Code"] = meta[isin_col].astype(str).str.strip() if isin_col else ""

    # Sector/Company override from SECTOR_FILE
    sector_file = Path(SECTOR_FILE)
    if sector_file.exists():
        xl = pd.read_csv(sector_file) if SECTOR_FILE.endswith(".csv") else pd.read_excel(sector_file)
        xl.columns = [c.strip() for c in xl.columns]
        xcols = {c.lower(): c for c in xl.columns}
        sym_c  = xcols.get("symbol")
        sec_c  = xcols.get("sector")
        comp_c = xcols.get("company name")
        if sym_c and sec_c:
            xl[sym_c] = xl[sym_c].astype(str).str.strip().str.upper()
            meta["Industry"] = meta["Ticker"].map(
                dict(zip(xl[sym_c], xl[sec_c].astype(str).str.strip()))
            ).fillna(meta["Industry"])
        if sym_c and comp_c:
            xl[sym_c] = xl[sym_c].astype(str).str.strip().str.upper()
            meta["Company Name"] = meta["Ticker"].map(
                dict(zip(xl[sym_c], xl[comp_c].astype(str).str.strip()))
            ).fillna(meta["Company Name"])

    return meta[["Ticker", "Company Name", "Industry", "ISIN Code"]].drop_duplicates("Ticker").reset_index(drop=True)


# ─── SCORING ENGINE ───────────────────────────────────────────────────────────

def compute_scores(prices_long, meta_df):
    prices_long = prices_long.copy()
    prices_long["Date"]   = pd.to_datetime(prices_long["Date"])
    prices_long["Ticker"] = prices_long["Ticker"].astype(str).str.strip().str.upper()
    prices_long.drop_duplicates(subset=["Date", "Ticker"], inplace=True)

    prices = prices_long.pivot(index="Date", columns="Ticker", values="Close").sort_index()
    prices.dropna(axis=1, how="all", inplace=True)

    # Monthly momentum (product of monthly returns)
    month_close = prices.groupby(prices.index.strftime("%Y-%m")).tail(1)
    month_start = prices.groupby(prices.index.strftime("%Y-%m")).head(1)
    month_start.index = month_close.index
    MOM  = ((month_close - month_start) / month_start + 1).product() - 1
    mom  = MOM * 100

    # FIP (Fraction In Profit)
    daily_ret      = prices.pct_change(fill_method=None)
    positive_change = (daily_ret > 0).sum() / daily_ret.count() * 100
    negative_change = (daily_ret < 0).sum() / daily_ret.count() * 100

    # Combined rank: RankMom + FIPrank (only for positive-momentum stocks)
    result = pd.concat([positive_change, negative_change, mom], axis=1, join="inner")
    result.columns = ["Positive", "Negative", "Momentum"]
    result = result.reset_index()
    result["Ticker"]  = result["Ticker"].astype(str).str.strip().str.upper()
    result["RankMom"] = result["Momentum"].rank(method="min", ascending=False)
    result["FIP"]     = result.apply(
        lambda row: row["Negative"] - row["Positive"] if row["Momentum"] > 0 else np.nan, axis=1)

    result_pos = result.dropna(subset=["FIP"]).copy()
    result_pos["FIPrank"]      = result_pos["FIP"].rank(method="first", ascending=True)
    result_pos["CombinedRank"] = result_pos["RankMom"] + result_pos["FIPrank"]
    result_pos = result_pos.sort_values("CombinedRank", ascending=True).reset_index(drop=True)
    result_pos["RealRank"] = range(1, len(result_pos) + 1)

    # Last known price
    try:
        last_prices = {str(k).strip().upper(): v
                       for k, v in prices.tail(1).iloc[0].to_dict().items()}
    except Exception:
        last_prices = {}

    # Percentile score 0-100 across positive-momentum stocks (by momentum magnitude)
    pos_syms_sorted = result_pos.sort_values("Momentum", ascending=False)["Ticker"].tolist()
    n_pos = len(pos_syms_sorted)
    score_map = {sym: round(((n_pos - (i + 1)) / max(n_pos - 1, 1)) * 100, 2)
                 for i, sym in enumerate(pos_syms_sorted)}

    rank_map = dict(zip(result_pos["Ticker"], result_pos["RealRank"].astype(int)))

    def get_band(s, m):
        if m <= 0:  return "Weak Momentum (<=0)"
        if s >= 80: return "Strong (80-100)"
        if s >= 60: return "Good (60-80)"
        if s >= 40: return "Average (40-60)"
        return "Weak (0-40)"

    meta_idx = meta_df.set_index("Ticker")
    records  = []
    for sym in meta_df["Ticker"].str.upper().tolist():
        company  = str(meta_idx.at[sym, "Company Name"]) if sym in meta_idx.index else ""
        industry = str(meta_idx.at[sym, "Industry"])     if sym in meta_idx.index else "Unclassified"
        price    = round(float(last_prices.get(sym, 0)), 2)

        if sym not in mom.index:
            records.append({"symbol": sym, "company": company, "industry": industry,
                            "score": "N/A", "momentum": "N/A", "positive": "N/A",
                            "negative": "N/A", "band": "N/A", "rank": "N/A", "price": price})
            continue

        m = round(float(mom[sym]), 2)
        s = score_map.get(sym, 0.0)
        records.append({
            "symbol":   sym,
            "company":  company,
            "industry": industry,
            "score":    s if m > 0 else 0,
            "momentum": m,
            "positive": round(float(positive_change.get(sym, 0)), 1),
            "negative": round(float(negative_change.get(sym, 0)), 1),
            "band":     get_band(s if m > 0 else 0, m),
            "rank":     rank_map.get(sym, "N/A"),
            "price":    price,
        })

    records.sort(key=lambda x: 999999 if isinstance(x["rank"], str) else x["rank"])
    return records


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    today       = date.today()
    end_date    = today
    start_date  = (datetime.combine(today, datetime.min.time()) -
                   relativedelta(months=LOOKBACK_MONTHS)).date()
    month_key   = today.strftime("%Y-%m")
    month_label = today.strftime("%b %Y")

    print(f"\n{'='*50}")
    print(f"  Momentum Refresh — {month_label}")
    print(f"  Lookback : {start_date} → {end_date}")
    print(f"{'='*50}\n")

    meta        = load_universe()
    symbol_list = meta["Ticker"].tolist()
    print(f"Universe loaded: {len(symbol_list)} symbols\n")

    if TRUEDATA_AVAILABLE:
        print("Using TrueData...")
        raw, errors = fetch_truedata(TD_USERNAME, TD_PASSWORD, symbol_list)
    else:
        print("TrueData not found — using yfinance fallback...")
        raw, errors = fetch_yfinance(symbol_list, start_date, end_date)

    if errors:
        logging.warning(f"Failed tickers ({len(errors)}): {errors[:20]}")
    if raw.empty:
        raise RuntimeError("No price data fetched. Check credentials and universe file.")

    raw["Date"]   = pd.to_datetime(raw["Date"])
    raw["Ticker"] = raw["Ticker"].astype(str).str.strip().str.upper()
    raw = raw[(raw["Date"] >= pd.Timestamp(start_date)) &
              (raw["Date"] <= pd.Timestamp(end_date))].copy()

    lookback_label   = f"{start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')}"
    price_date_label = raw["Date"].max().strftime("%d %b %Y")

    universe = compute_scores(raw, meta)

    # ── Save CSV
    pd.DataFrame(universe).to_csv(OUTPUT_CSV, index=False)
    print(f"\nCSV  → {OUTPUT_CSV}")

    # ── Save JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump([{
            "key":        month_key,
            "label":      month_label,
            "price_date": price_date_label,
            "lookback":   lookback_label,
            "universe":   universe,
        }], f, ensure_ascii=False, indent=2)
    print(f"JSON → {OUTPUT_JSON}")

    total    = len(universe)
    positive = sum(1 for u in universe if isinstance(u["momentum"], float) and u["momentum"] > 0)
    na_count = sum(1 for u in universe if u["band"] == "N/A")
    print(f"\nTotal: {total} | Positive momentum: {positive} | N/A: {na_count}")
    print(f"\n✅ Done. Upload {OUTPUT_JSON} via 📥 Upload Rankings in the HTML app.")


if __name__ == "__main__":
    main()