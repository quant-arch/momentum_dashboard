# =============================================================================
# may_momentum.py
# Combined pipeline: Monthly Momentum → Daily Momentum → Ratios & KPIs →
#                   Ratios-Manan (Beta) → Momentum Prod (Maxfolio)
#
# Run order per readme_seq.txt:
#   1. PART 1 – Monthly Momentum (once a month, check end_date)
#   2. PART 2 – Daily Momentum  (every day)
#   3. PART 3 – Ratios & KPIs  (every day, after Part 2)
#   4. PART 4 – Ratios-Manan / Beta (every day, after Part 3)
#   5. PART 5 – Momentum Prod / Maxfolio (every day, after Part 4)
# =============================================================================

import time
import logging
import os
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path

# Require the TrueData client (TD_hist). Do not fall back to other providers.
try:
    from truedata import TD_hist
except Exception:
    raise ImportError(
        "TrueData client not found. This script requires the TrueData `truedata` client\n"
        "so that `from truedata import TD_hist` succeeds.\n"
        "Please install or add your TrueData client to the active virtualenv/PYTHONPATH.\n"
        "If you don't have the client, obtain it from your TrueData provider or restore the\n"
        "original `truedata` module used in your environment.\n"
    )

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR   = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover"
NEW_MONTHLY_DIR = os.path.join(BASE_DIR, "new_monthly")
TRIALS_DIR      = os.path.join(BASE_DIR, "Trials")
RATIOS_DIR      = os.path.join(BASE_DIR, "Ratios And KPIs")

# ---------------------------------------------------------------------------
# Shared Helper: fetch_truedata_history
# ---------------------------------------------------------------------------
def fetch_truedata_history(ticker_list, duration="1 Y", bar_size="EOD",
                           sleep_time=0.1):
    """Fetch EOD history from TrueData for a list of tickers."""
    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
    td_hist = TD_hist(username, password)
    df_list, error_list = [], []
    for ticker in ticker_list:
        try:
            df = td_hist.get_historic_data([ticker], duration=duration,
                                           bar_size=bar_size)
            df["Ticker"] = ticker
            rename = {}
            for col in ["timestamp", "datetime", "date"]:
                if col in df.columns:
                    rename[col] = "Date"
                    break
            rename.update({"high": "High", "low": "Low",
                           "close": "Close", "open": "Open"})
            df = df.rename(columns=rename)
            df_list.append(df)
            logging.info(f"Fetched {ticker} ({len(df)} rows).")
            time.sleep(sleep_time)
        except Exception as e:
            logging.error(f"Failed {ticker}: {e}")
            error_list.append(ticker)
    final_df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
    return final_df, error_list


def _sanitize_price_df(df):
    """Ensure a fetched price DataFrame has `Date`, `Ticker`, `Close` columns.
    Tries common column name variants and drops rows without a valid date.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    # Normalize column names
    cols_lower = {c.lower(): c for c in df.columns}
    # date column
    if "date" in cols_lower:
        df["Date"] = pd.to_datetime(df[cols_lower["date"]])
    elif "datetime" in cols_lower:
        df["Date"] = pd.to_datetime(df[cols_lower["datetime"]])
    elif "timestamp" in cols_lower:
        df["Date"] = pd.to_datetime(df[cols_lower["timestamp"]])
    # ensure Close
    if "close" in cols_lower:
        df["Close"] = df[cols_lower["close"]]
    elif "adj close" in cols_lower:
        df["Close"] = df[cols_lower["adj close"]]
    # Ticker should already be present from the fetcher, but try to recover
    if "ticker" not in df.columns and "symbol" in cols_lower:
        df["Ticker"] = df[cols_lower["symbol"]]

    # Drop rows without a parsable date
    if "Date" in df.columns:
        df = df.dropna(subset=["Date"]).copy()
    # Keep only expected columns
    keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Ticker"] if c in df.columns]
    return df[keep]
# =============================================================================

def run_momentum_strategy(universe_file, start_date, end_date, top_n,
                          output_root):
    """Rolling-window momentum strategy; saves per-window + master xlsx."""
    if universe_file.endswith(".csv"):
        stock_list = pd.read_csv(universe_file)[["Symbol", "ISIN Code"]]
    else:
        stock_list = pd.read_excel(universe_file)[["Symbol", "ISIN Code"]]

    stock_list["Ticker"] = stock_list["Symbol"]
    symbol_list  = stock_list["Symbol"].tolist()
    universe_name = Path(universe_file).stem
    output_dir   = os.path.join(output_root,
                                f"{universe_name}_{top_n}_stocks_results")
    os.makedirs(output_dir, exist_ok=True)

    total_start = pd.to_datetime(start_date)
    total_end   = pd.to_datetime(end_date)

    print(f"\n📥 Downloading price data for {len(symbol_list)} symbols …")
    data, errors = fetch_truedata_history(symbol_list, duration="10 Y",
                                          bar_size="EOD")
    data = data[["Date", "Close", "Ticker"]]
    data.drop_duplicates(subset=["Date", "Ticker"], inplace=True)
    print("Failed tickers:", errors)
    prices_all = data.pivot(index="Date", columns="Ticker",
                            values="Close").sort_index()

    # Build rolling 6-month windows (slide by 1 month)
    windows = []
    cur = total_start
    while True:
        end_w = cur + relativedelta(months=6)
        if end_w > total_end:
            break
        wp = prices_all.loc[(prices_all.index >= cur) &
                             (prices_all.index < end_w)].copy()
        if not wp.empty:
            windows.append((cur, end_w, wp))
        cur += relativedelta(months=1)
    print(f"📊 Created {len(windows)} rolling windows.")

    for start_w, end_w, prices in windows:
        suffix = f"{start_w.strftime('%Y%m%d')}_{end_w.strftime('%Y%m%d')}"
        prices.dropna(axis=1, how="all", inplace=True)
        if prices.empty:
            continue

        monthclose = prices.groupby(prices.index.strftime("%Y-%m")).tail(1)
        monthstart = prices.groupby(prices.index.strftime("%Y-%m")).head(1)
        monthstart.index = monthclose.index
        monchange  = (monthclose - monthstart) / monthstart
        MOM        = (monchange + 1).product() - 1
        mom        = MOM * 100

        daily_ret     = prices.pct_change(fill_method=None)
        positivechange = (daily_ret[daily_ret > 0].count() /
                          daily_ret.count()) * 100
        negativechange = (daily_ret[daily_ret < 0].count() /
                          daily_ret.count()) * 100

        result = pd.concat([positivechange, negativechange, mom],
                           axis=1, join="inner")
        result.columns = ["Positive", "Negative", "Momentum"]
        result = result.reset_index().rename(columns={"index": "Ticker"})
        result = pd.merge(result, stock_list[["Ticker", "ISIN Code"]],
                          on="Ticker", how="left")

        df = result.copy()
        df["Rank_Mom"] = df["Momentum"].rank(method="min", ascending=False)
        df["FIP"] = df.apply(
            lambda r: r["Negative"] - r["Positive"]
            if r["Momentum"] > 0 else np.nan, axis=1)
        df.dropna(inplace=True)
        df["FIP_rank"]     = df["FIP"].rank(method="first", ascending=True)
        df["Combined_Rank"] = df["Rank_Mom"] + df["FIP_rank"]

        if end_w.strftime("%Y-%m-%d") == "2026-01-01":
            df = df[~df["Ticker"].isin(["MARUTI", "PTCIL"])]

        df = df.sort_values("Combined_Rank", ascending=True)

        # CMP filter: exclude stocks >= ₹7500, but whitelist known hedge tickers
        HEDGE_WHITELIST = {"LIQUIDCASE"}
        last_close = prices.iloc[-1]
        df["CMP"] = df["Ticker"].map(last_close.to_dict())
        excluded = df[(df["CMP"] >= 7500) & (~df["Ticker"].isin(HEDGE_WHITELIST))]["Ticker"].tolist()
        if excluded:
            print(f"⚠️  Excluded (CMP ≥ ₹7500): {excluded}")
        # keep rows with CMP < 7500 OR those on the hedge whitelist
        df = df[(df["CMP"] < 7500) | (df["Ticker"].isin(HEDGE_WHITELIST))].head(top_n)

        df["Real_Rank"] = range(1, len(df) + 1)
        df["End_Date"]  = end_w.strftime("%Y-%m-%d")
        df.to_excel(os.path.join(output_dir, f"momentum_{suffix}.xlsx"),
                    index=False)
        print(f"✅ Window {start_w.date()} → {end_w.date()} saved.")

    # Master summary
    master_data = []
    for f in os.listdir(output_dir):
        if f.startswith("momentum_") and f.endswith(".xlsx"):
            tmp = pd.read_excel(os.path.join(output_dir, f))
            master_data.append(tmp[["End_Date", "ISIN Code",
                                    "Ticker", "Real_Rank"]])
    if master_data:
        master_df   = pd.concat(master_data, ignore_index=True)
        master_path = os.path.join(output_dir, "master_momentum_summary.xlsx")
        master_df.to_excel(master_path, index=False)
        print(f"✅ Master file: {master_path}")
        return master_path
    return None


def run_part1():
    """Entry point for PART 1 – Monthly Momentum (top 20 for May)."""
    print("\n" + "="*70)
    print("PART 1 – MONTHLY MOMENTUM  (Monthly_momentum.ipynb)")
    print("="*70)
    master = run_momentum_strategy(
        universe_file=os.path.join(NEW_MONTHLY_DIR,
                                   "ticker_master_may26.xlsx"),
        start_date="2022-06-01",
        end_date="2026-05-01",   # ← adjust month each month
        top_n=20,                # top 20 stocks for May
        output_root=NEW_MONTHLY_DIR,
    )
    print("Master summary:", master)


# =============================================================================
# PART 2 – DAILY MOMENTUM  (Momentum daily_april_rebalance.ipynb)
# Output: C:\...\Trials\Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx
# NOTE:   Run every day after markets close.
# =============================================================================

def process_portfolio_daily(nav_df, ticker_data, initial_value=75,
                            inception_date=None, output_file=None):
    """Month-by-month rebalancing portfolio with inception date support."""
    df_lis = []
    last_month_value    = {}
    last_month_quantity = {}

    nav_df      = nav_df.sort_values(["Date", "Ticker"]).copy()
    nav_df["Date"] = pd.to_datetime(nav_df["Date"])
    ticker_data = ticker_data.sort_values(["Ticker", "Date"]).copy()
    ticker_data["Date"] = pd.to_datetime(ticker_data["Date"])

    if inception_date is None:
        inception_date = nav_df["Date"].min()
    else:
        inception_date = pd.to_datetime(inception_date)

    for year_month in nav_df["Year-Month"].drop_duplicates():
        month_nav      = nav_df[nav_df["Year-Month"] == year_month].copy()
        tickers        = month_nav["Ticker"].dropna().unique().tolist()
        selection_date = pd.to_datetime(month_nav["Date"].min())
        ym_date        = pd.to_datetime(f"{year_month}-01")

        prev_start = ym_date - relativedelta(months=2)
        curr_start = ym_date
        curr_end   = ym_date + pd.offsets.MonthEnd(0)

        stock_data = ticker_data[
            (ticker_data["Date"] >= prev_start) &
            (ticker_data["Date"] <= curr_end) &
            (ticker_data["Ticker"].isin(tickers))
        ].copy()
        stock_data = stock_data[stock_data["Date"] >= inception_date].copy()
        stock_data["%change"] = stock_data.groupby("Ticker")["Close"].pct_change()

        stock_data_flt = stock_data[
            (stock_data["Date"] >= curr_start) &
            (stock_data["Date"] <= curr_end)
        ].copy()
        if stock_data_flt.empty:
            continue

        if not last_month_value:
            alloc = initial_value / len(tickers)
            stock_allocations = {t: alloc for t in tickers}
        else:
            stock_allocations = {t: last_month_value[t]
                                 for t in tickers if t in last_month_value}
            dropped = [t for t in last_month_value if t not in tickers]
            dropped_val = sum(last_month_value[t] for t in dropped)
            new_stocks  = [t for t in tickers if t not in last_month_value]
            if new_stocks:
                per = dropped_val / len(new_stocks) if dropped_val else 0.0
                for t in new_stocks:
                    stock_allocations[t] = per

        for ticker, init_val in stock_allocations.items():
            idx = stock_data_flt[stock_data_flt["Ticker"] == ticker].index
            tkr = stock_data_flt.loc[idx]
            if tkr.empty:
                continue
            stock_data_flt.loc[idx, "Initial_Allocation"] = init_val
            stock_data_flt.loc[idx, "Selection_Date"]     = selection_date
            stock_data_flt.loc[idx, "Buy_Hold_Value"] = init_val * (
                (1 + stock_data_flt.loc[idx, "%change"].fillna(0)).cumprod()
            )
            buy_price = float(tkr.iloc[0]["Close"])
            quantity  = last_month_quantity.get(
                ticker, init_val / buy_price if buy_price else 0.0)
            stock_data_flt.loc[idx, "Buy_Price"] = buy_price
            stock_data_flt.loc[idx, "Quantity"]  = quantity
            if "Real_Rank" in month_nav.columns:
                rr = month_nav.loc[month_nav["Ticker"] == ticker, "Real_Rank"]
                if not rr.empty:
                    stock_data_flt.loc[idx, "Real_Rank"] = rr.iloc[0]

        last_month_quantity = (
            stock_data_flt.groupby("Ticker")["Quantity"].last().to_dict())
        last_month_value = (
            stock_data_flt.groupby("Ticker")["Buy_Hold_Value"].last().to_dict())
        stock_data_flt["Total_Portfolio_Value"] = (
            stock_data_flt.groupby("Date")["Buy_Hold_Value"]
            .transform("sum"))
        df_lis.append(stock_data_flt)

    if not df_lis:
        return pd.DataFrame()
    final_df = (pd.concat(df_lis, ignore_index=True)
                .sort_values(["Date", "Ticker"])
                .reset_index(drop=True))
    if output_file:
        final_df.to_excel(output_file, index=False)
    return final_df


def build_weighted_hedge_segment(hedge_prices, start_date, end_date,
                                 base_values, segment_name):
    seg = hedge_prices[
        (hedge_prices["Date"] >= start_date) &
        (hedge_prices["Date"] <= end_date) &
        (hedge_prices["Ticker"].isin(base_values))
    ][["Date", "Ticker", "Open", "Close"]].copy()
    if seg.empty:
        return seg
    seg = seg.sort_values(["Ticker", "Date"])
    seg["%change"]            = seg.groupby("Ticker")["Close"].pct_change()
    seg["Initial_Allocation"] = seg["Ticker"].map(base_values)
    seg["ret_factor"]         = 1 + seg["%change"].fillna(0)
    seg["cum_factor"]         = seg.groupby("Ticker")["ret_factor"].cumprod()
    seg["Buy_Hold_Value"]     = seg["Initial_Allocation"] * seg["cum_factor"]
    buy_prices                = seg.groupby("Ticker")["Close"].transform("first")
    seg["Buy_Price"]          = buy_prices
    seg["Quantity"]           = np.where(buy_prices > 0,
                                         seg["Initial_Allocation"] / buy_prices, 0.0)
    seg["Selection_Date"]     = start_date
    seg["Hedge_Segment"]      = segment_name
    seg["Total_Portfolio_Value"] = (
        seg.groupby("Date")["Buy_Hold_Value"].transform("sum"))
    return seg.drop(columns=["ret_factor", "cum_factor"])


def build_rebalanced_hedge_book(base_portfolio_df, portfolio_end_date=None,
                                default_hedge_value=25.0):
    if portfolio_end_date is None:
        portfolio_end_date = pd.to_datetime(base_portfolio_df["Date"]).max()
    else:
        portfolio_end_date = pd.to_datetime(portfolio_end_date)

    cutoff = pd.Timestamp("2025-11-30")
    if portfolio_end_date <= cutoff:
        return pd.DataFrame()

    seed_rows = base_portfolio_df[
        (base_portfolio_df["Ticker"] == "GOLDBEES") &
        (base_portfolio_df["Date"] <= cutoff)
    ].sort_values("Date")
    hedge_seed = (float(seed_rows["Buy_Hold_Value"].iloc[-1])
                  if not seed_rows.empty else default_hedge_value)

    hedge_prices = fetch_truedata_history(
        ["GOLDBEES", "SILVERBEES", "MOGSEC", "LIQUIDCASE"],
        duration="5 Y", bar_size="EOD", sleep_time=0.1)[0]

    segments = []

    # Dec-25 → Jan-26
    ds = pd.Timestamp("2025-12-01")
    de = min(pd.Timestamp("2026-01-31"), portfolio_end_date)
    if portfolio_end_date >= ds:
        df_dj = build_weighted_hedge_segment(
            hedge_prices, ds, de,
            {"GOLDBEES": 0.60*hedge_seed, "SILVERBEES": 0.20*hedge_seed,
             "MOGSEC": 0.20*hedge_seed},
            "2025-12_to_2026-01")
        if not df_dj.empty:
            segments.append(df_dj)
    else:
        df_dj = pd.DataFrame()

    # Feb-26
    fs = pd.Timestamp("2026-02-01")
    fe = min(pd.Timestamp("2026-02-28"), portfolio_end_date)
    if portfolio_end_date >= fs and not df_dj.empty:
        feb_seed = (df_dj.groupby("Date", as_index=False)["Buy_Hold_Value"]
                    .sum().sort_values("Date")["Buy_Hold_Value"].iloc[-1])
        df_feb = build_weighted_hedge_segment(
            hedge_prices, fs, fe,
            {"GOLDBEES": 0.40*feb_seed, "MOGSEC": 0.60*feb_seed},
            "2026-02")
        if not df_feb.empty:
            segments.append(df_feb)
    else:
        df_feb = pd.DataFrame()

    # Mar-26 onward
    ms = pd.Timestamp("2026-03-01")
    if portfolio_end_date >= ms and not df_feb.empty:
        feb_last_date = df_feb["Date"].max()
        feb_last = (df_feb[df_feb["Date"] == feb_last_date]
                    .set_index("Ticker")["Buy_Hold_Value"].to_dict())
        mar_vals = {
            "GOLDBEES":   feb_last.get("GOLDBEES", 0.0),
            "LIQUIDCASE": feb_last.get("MOGSEC",   0.0),
        }
        df_mar = build_weighted_hedge_segment(
            hedge_prices, ms, portfolio_end_date, mar_vals, "2026-03_onward")
        if not df_mar.empty:
            segments.append(df_mar)

    if not segments:
        return pd.DataFrame()
    return (pd.concat(segments, ignore_index=True)
            .sort_values(["Date", "Ticker"])
            .reset_index(drop=True))


def prepare_and_process_portfolio_daily(input_file, start_date, end_date,
                                        output_folder):
    """Load master momentum file, process equity + gold portfolio."""
    nav_raw = pd.read_excel(input_file).rename(columns={"End_Date": "Date"})
    nav_raw["Date"] = pd.to_datetime(nav_raw["Date"])

    sel_cols = ["Date", "Ticker"]
    if "Real_Rank" in nav_raw.columns:
        sel_cols.append("Real_Rank")

    nav_df = (nav_raw[(nav_raw["Date"] >= start_date) &
                      (nav_raw["Date"] <= end_date)]
              .reset_index(drop=True)[sel_cols])
    nav_df["Year-Month"] = nav_df["Date"].dt.to_period("M").astype(str)

    goldbees = pd.DataFrame({
        "Date":   nav_df["Date"].drop_duplicates().sort_values(),
        "Ticker": "GOLDBEES"
    })
    if "Real_Rank" in nav_df.columns:
        goldbees["Real_Rank"] = np.nan
    goldbees["Year-Month"] = (pd.to_datetime(goldbees["Date"])
                               .dt.to_period("M").astype(str))

    concat_df = (pd.concat([nav_df, goldbees], ignore_index=True)
                 .sort_values(["Date", "Ticker"]).reset_index(drop=True))

    ticker_df   = concat_df.query("Ticker != 'GOLDBEES'")
    gold_df     = concat_df.query("Ticker == 'GOLDBEES'")
    inception   = pd.to_datetime(start_date)

    td_equity = fetch_truedata_history(
        ticker_df["Ticker"].unique().tolist(),
        duration="10 Y", bar_size="EOD", sleep_time=0.1)[0]
    td_gold = fetch_truedata_history(
        ["GOLDBEES"], duration="10 Y", bar_size="EOD", sleep_time=0.1)[0]
    

    # sanitize fetched price tables and produce processed daily frames
    td_equity = _sanitize_price_df(td_equity)
    td_gold = _sanitize_price_df(td_gold)

    if td_equity.empty:
        logging.error("No equity price data fetched; aborting daily portfolio processing.")
        df_equity = pd.DataFrame()
    else:
        df_equity = process_portfolio_daily(ticker_df, td_equity, 75,
                                            inception_date=inception)

    if td_gold.empty:
        logging.error("No gold price data fetched; skipping gold portfolio.")
        df_gold = pd.DataFrame()
    else:
        df_gold = process_portfolio_daily(gold_df, td_gold, 25,
                                          inception_date=inception)

    final_df = (pd.concat([df_equity, df_gold], ignore_index=True)
                .sort_values(["Date", "Ticker"]).reset_index(drop=True))
    os.makedirs(output_folder, exist_ok=True)
    middle = os.path.basename(os.path.dirname(input_file))
    out_file = os.path.join(output_folder,
                            f"{middle}_GoldSilverDebt_buy&hold_returns.xlsx")
    final_df.to_excel(out_file, index=False)
    print(f"✅ Daily output: {out_file}")
    return final_df


def run_part2():
    """Entry point for PART 2 – Daily Momentum."""
    print("\n" + "="*70)
    print("PART 2 – DAILY MOMENTUM  (Momentum daily_april_rebalance.ipynb)")
    print("="*70)
    input_file = os.path.join(
        BASE_DIR, "Stocks",
        "Nifty_500_2025_Apr_20_stocks_results",
        "master_momentum_summary.xlsx")
    final_df = prepare_and_process_portfolio_daily(
        input_file  = input_file,
        start_date  = "2023-04-01",
        end_date    = date.today().strftime("%Y-%m-%d"),
        output_folder = TRIALS_DIR,
    )

    # Strip GOLDBEES rows after Nov-2025 (they are replaced by the hedge book)
    old_df = final_df[
        ~((final_df["Date"] > "2025-11-30") & (final_df["Ticker"] == "GOLDBEES"))
    ].copy()

    # Build hedge book for post-Nov-2025 period (GOLDBEES/SILVERBEES/MOGSEC/LIQUIDCASE)
    hedge_df = build_rebalanced_hedge_book(final_df)

    # Concatenate equity+gold (old) with hedge book and save final buy&hold file
    conc_df = pd.concat([old_df, hedge_df], ignore_index=True) if not hedge_df.empty else old_df
    conc_df = conc_df.sort_values(["Date", "Ticker"]).reset_index(drop=True)

    # Create a separate hedge-only section covering Nov-2025 through 2026-04-30
    try:
        hedge_section = pd.DataFrame()
        if not hedge_df.empty:
            hedge_section = hedge_df[(hedge_df["Date"] > "2025-11-30") & (hedge_df["Date"] <= "2026-04-30")].copy()
        os.makedirs(TRIALS_DIR, exist_ok=True)
        hedge_file = os.path.join(TRIALS_DIR, "Nifty_500_2025_Apr_20_stocks_results_Hedge_Nov2025_Apr2026.xlsx")
        hedge_section.to_excel(hedge_file, index=False)
        print(f"✅ Hedge section saved: {hedge_file}")
    except Exception as e:
        logging.error(f"Failed saving hedge section: {e}")

    # Dump debug files so we can inspect hedge rows (e.g. LIQUIDCASE)
    try:
        old_df.to_excel(os.path.join(TRIALS_DIR, "old_df_debug.xlsx"), index=False)
    except Exception:
        pass
    if not hedge_df.empty:
        try:
            hedge_df.to_excel(os.path.join(TRIALS_DIR, "hedge_debug.xlsx"), index=False)
        except Exception:
            pass

    # Save/append final buy-hold using safe-append semantics (freeze through Apr 30, 2026)
    buyhold_out = os.path.join(
        TRIALS_DIR,
        "Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")
    # Persist final buy-hold using safe-append semantics
    try:
        safe_append_buyhold(buyhold_out, conc_df, cutoff_date="2026-04-30", append_end="2026-05-31")
    except Exception as e:
        logging.error(f"Failed to safe-append buy-hold file: {e}")
    


    # processed daily results are produced inside prepare_and_process_portfolio_daily()

def safe_append_buyhold(path, new_df, cutoff_date="2026-04-30", append_end="2026-05-31"):
    """Freeze existing buy-hold rows through `cutoff_date` and append rows
    from `new_df` that are after the cutoff up to `append_end`. Saves result
    to `path`.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = new_df.copy()
    if "Date" not in new.columns or "Ticker" not in new.columns:
        raise ValueError("new_df must contain 'Date' and 'Ticker' columns")
    new["Date"] = pd.to_datetime(new["Date"])
    cutoff = pd.to_datetime(cutoff_date)
    append_end_ts = pd.to_datetime(append_end)

    if os.path.exists(path):
        existing = pd.read_excel(path)
        existing["Date"] = pd.to_datetime(existing["Date"])
        frozen = existing[existing["Date"] <= cutoff].copy()
    else:
        frozen = pd.DataFrame(columns=new.columns)

    # select candidate rows from the newly generated dataframe
    may_rows = new[(new["Date"] > cutoff) & (new["Date"] <= append_end_ts)].copy()

    # drop any rows that are already present in the frozen set (by Date+Ticker)
    key_cols = ["Date", "Ticker"]
    if not frozen.empty and not may_rows.empty:
        try:
            may_rows = may_rows[~may_rows.set_index(key_cols).index.isin(
                frozen.set_index(key_cols).index
            )].reset_index(drop=True)
        except Exception:
            # if index alignment fails for any reason, fall back to concat-then-dedup
            concat_tmp = pd.concat([frozen, may_rows], ignore_index=True)
            concat_tmp = concat_tmp.drop_duplicates(subset=key_cols, keep="first")
            concat_tmp.to_excel(path, index=False)
            print(f"✅ Buy-Hold file saved: {path}")
            return

    out = pd.concat([frozen, may_rows], ignore_index=True, sort=False)
    out = out.sort_values(["Date", "Ticker"]).reset_index(drop=True)
    out.to_excel(path, index=False)
    print(f"✅ Buy-Hold file saved: {path}")


# =============================================================================
# PART 3 – RATIOS AND KPIs  (Ratios and KPIs.ipynb)
# Output: C:\...\Ratios And KPIs\<returns_file_renamed_ratios>.xlsx
# NOTE:   Run every day after PART 2.
# =============================================================================

def calculate_momentum_ratios(returns_file, benchmark_file):
    """Calculate rolling returns, SD, Sharpe, alpha vs benchmark."""
    benchmark = pd.read_excel(benchmark_file).rename(
        columns={"Buy_Hold_Value": "benchmark_value"})
    benchmark["pct_change_benchmark"] = benchmark["benchmark_value"].pct_change()
    benchmark["Rolling_Returns_252_benchmark"] = (
        (1 + benchmark["pct_change_benchmark"])
        .rolling(252).apply(np.prod, raw=True) - 1)

    df = (pd.read_excel(returns_file, usecols=["Date", "Buy_Hold_Value"])
          .rename(columns={"Buy_Hold_Value": "value"}))
    grouped = df.groupby("Date", as_index=False)["value"].sum()
    grouped["pct_change_value"]   = grouped["value"].pct_change()
    grouped["Rolling_Returns_252"] = (
        (1 + grouped["pct_change_value"])
        .rolling(252).apply(np.prod, raw=True) - 1)

    merged = grouped.merge(benchmark, on="Date", how="left")
    merged["Rolling_Returns_alpha_252"] = (
        merged["Rolling_Returns_252"] -
        merged["Rolling_Returns_252_benchmark"])
    merged["Rolling_Returns_alpha_cumsum_252"] = (
        merged["Rolling_Returns_alpha_252"].cumsum())

    for w in [21, 63, 126, 252, 504]:
        merged[f"SD_{w}"] = (
            merged["pct_change_value"].rolling(w).std() * np.sqrt(252))
    merged["Sharpe_252"] = (
        (merged["Rolling_Returns_252"] - 0.05) / merged["SD_252"])

    os.makedirs(RATIOS_DIR, exist_ok=True)
    base_name   = os.path.basename(returns_file)
    output_file = base_name.replace("returns", "ratios")
    merged.to_excel(os.path.join(RATIOS_DIR, output_file), index=False)
    print(f"✅ Ratios saved: {output_file}")
    return output_file


def run_part3():
    """Entry point for PART 3 – Ratios and KPIs."""
    print("\n" + "="*70)
    print("PART 3 – RATIOS AND KPIs  (Ratios and KPIs.ipynb)")
    print("="*70)
    returns_file   = os.path.join(
        TRIALS_DIR,
        "Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")
    benchmark_file = os.path.join(
        TRIALS_DIR,
        "nse500_Nifty_500_2025_Apr_nse500_nse500_nse500_nse500_nse500_returns.xlsx")
    calculate_momentum_ratios(returns_file, benchmark_file)
    print("PART 3 done.")


# =============================================================================
# PART 4 – RATIOS-MANAN / PORTFOLIO BETA  (Ratios-Manan.ipynb)
# Output: C:\...\momentum_ratios.xlsx  (same folder as notebook)
# NOTE:   Run every day after PART 3.
# =============================================================================

def calculate_portfolio_beta(ticker_data_df, benchmark_name,
                              weights_dict=None):
    """Compute portfolio beta vs benchmark using last 252 days."""
    df = ticker_data_df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    price_df = (df.pivot(index="Date", columns="Ticker", values="Close")
                .sort_index())
    price_df = price_df.loc[
        price_df.index >= price_df.index.max() - pd.Timedelta(days=252)]

    returns      = price_df.pct_change().dropna()
    stock_ret    = returns.drop(columns=[benchmark_name])
    bench_ret    = returns[benchmark_name]

    if weights_dict is None:
        n = stock_ret.shape[1]
        weights_dict = {c: 1/n for c in stock_ret.columns}
    w = pd.Series(weights_dict).reindex(stock_ret.columns).fillna(0)

    port_ret   = (stock_ret * w).sum(axis=1)
    covariance = np.cov(port_ret, bench_ret)[0][1]
    variance   = np.var(bench_ret)
    beta       = covariance / variance
    return beta, port_ret, bench_ret


def run_part4(returns_xlsx=None):
    """Entry point for PART 4 – Ratios-Manan (Beta calculation)."""
    print("\n" + "="*70)
    print("PART 4 – RATIOS-MANAN / BETA  (Ratios-Manan.ipynb)")
    print("="*70)

    # Load the latest buy-hold returns file to get current tickers & weights
    if returns_xlsx is None:
        returns_xlsx = os.path.join(
            TRIALS_DIR,
            "Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")

    data = pd.read_excel(returns_xlsx)
    max_date = data["Date"].max()
    max_date_tickers = data[data["Date"] == max_date].copy()

    total_val = max_date_tickers["Buy_Hold_Value"].sum()
    max_date_tickers["Weight"] = (
        max_date_tickers["Buy_Hold_Value"] / total_val)
    weights = dict(zip(max_date_tickers["Ticker"],
                       max_date_tickers["Weight"]))

    tickers = list(max_date_tickers["Ticker"].unique()) + ["NIFTY 500"]
    ticker_data = fetch_truedata_history(
        tickers, duration="2 Y", bar_size="EOD", sleep_time=0.1)[0]
    ticker_data = ticker_data[["Ticker", "Date", "Close"]].drop_duplicates(
        subset=["Ticker", "Date"])

    beta, _, _ = calculate_portfolio_beta(ticker_data, "NIFTY 500", weights)
    result_df  = pd.DataFrame({"Beta": [beta]})

    out_path = os.path.join(BASE_DIR, "momentum_ratios.xlsx")
    result_df.to_excel(out_path, index=False)
    print(f"✅ Portfolio Beta = {beta:.4f}  →  {out_path}")
    print("PART 4 done.")


# =============================================================================
# PART 5 – MOMENTUM PROD / MAXFOLIO  (Momentum prod from 11th Nov_march_rebalance.ipynb)
# Output: C:\...\Momentum_Maxfolio.xlsx  (same folder as notebook)
#         C:\...\Trials\Nifty_500_2025_Apr_20_stocks_results_gold_buy&hold_returns.xlsx
# NOTE:   Run every day after PART 4. Inception: 2025-11-11.
# =============================================================================

def process_portfolio_prod(nav_df, ticker_data, initial_value=75,
                           output_file=None):
    """Month-by-month rebalancing portfolio (Nov-2025 onward inception)."""
    df_lis = []
    last_month_value    = {}
    last_month_quantity = {}

    year_months = nav_df["Year-Month"].unique()
    for year_month in year_months:
        tickers   = nav_df[nav_df["Year-Month"] == year_month]["Ticker"].unique()
        ym_date   = pd.to_datetime(f"{year_month}-01")
        prev_start = (ym_date - relativedelta(months=2)).strftime("%Y-%m-%d")
        curr_start = ym_date.strftime("%Y-%m-%d")
        curr_end   = (ym_date + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")

        stock_data = ticker_data[
            (ticker_data["Date"] >= prev_start) &
            (ticker_data["Date"] <= curr_end) &
            (ticker_data["Ticker"].isin(tickers))
        ].copy()
        # Inception: only use data from 11-Nov-2025
        stock_data = stock_data[stock_data["Date"] >= "2025-11-11"]
        stock_data["%change"] = (
            stock_data.groupby("Ticker")["Close"].pct_change())

        stock_data_flt = stock_data[
            (stock_data["Date"] >= curr_start) &
            (stock_data["Date"] <= curr_end)
        ].copy()
        if stock_data_flt.empty:
            continue

        if not last_month_value:
            alloc = initial_value / len(tickers)
            stock_allocations = {t: alloc for t in tickers}
        else:
            stock_allocations = {t: last_month_value[t]
                                 for t in tickers if t in last_month_value}
            dropped    = [t for t in last_month_value if t not in tickers]
            dropped_val = sum(last_month_value[t] for t in dropped)
            new_stocks  = [t for t in tickers if t not in last_month_value]
            if new_stocks:
                per = dropped_val / len(new_stocks) if dropped_val else 0.0
                for t in new_stocks:
                    stock_allocations[t] = per

        for tkr, init_val in stock_allocations.items():
            idx = stock_data_flt[stock_data_flt["Ticker"] == tkr].index
            if len(idx) == 0:
                continue
            stock_data_flt.loc[idx, "Buy_Hold_Value"] = init_val * (
                (1 + stock_data_flt.loc[idx, "%change"].fillna(0)).cumprod())
            buy_price = stock_data_flt.loc[idx].iloc[0]["Close"]
            quantity  = (last_month_quantity.get(tkr, init_val / buy_price)
                         if buy_price else 0.0)
            stock_data_flt.loc[idx, "Buy_Price"] = buy_price
            stock_data_flt.loc[idx, "Quantity"]  = quantity

        last_month_quantity = (
            stock_data_flt.groupby("Ticker")["Quantity"].last().to_dict())
        last_month_value = (
            stock_data_flt.groupby("Ticker")["Buy_Hold_Value"].last().to_dict())
        stock_data_flt["Total_Portfolio_Value"] = (
            stock_data_flt.groupby("Date")["Buy_Hold_Value"].transform("sum"))
        df_lis.append(stock_data_flt)

    if not df_lis:
        return pd.DataFrame()
    final_df = pd.concat(df_lis).reset_index(drop=True)
    if output_file:
        final_df.to_excel(output_file, index=False)
    return final_df


def prepare_and_process_portfolio_prod(input_file, start_date, end_date,
                                       output_folder):
    """Prepare + process equity & gold portfolio for Momentum Prod."""
    nav_df = pd.read_excel(input_file).rename(columns={"End_Date": "Date"})
    nav_df["Date"] = pd.to_datetime(nav_df["Date"])
    nav_df = (nav_df[(nav_df["Date"] >= start_date) &
                     (nav_df["Date"] <= end_date)]
              .reset_index(drop=True)[["Date", "Ticker"]])
    nav_df["Year-Month"] = nav_df["Date"].dt.to_period("M").astype(str)

    goldbees = pd.DataFrame({
        "Date":   nav_df["Date"].unique(),
        "Ticker": "GOLDBEES"
    })
    goldbees["Year-Month"] = (pd.to_datetime(goldbees["Date"])
                               .dt.to_period("M").astype(str))

    concat_df = (pd.concat([nav_df, goldbees], ignore_index=True)
                 .sort_values(["Date", "Ticker"]).reset_index(drop=True))

    ticker_df = concat_df.query("Ticker != 'GOLDBEES'")
    gold_df   = concat_df.query("Ticker == 'GOLDBEES'")

    td_equity = fetch_truedata_history(
        ticker_df["Ticker"].unique().tolist(),
        duration="10 Y", bar_size="EOD", sleep_time=0.1)[0]
    td_gold = fetch_truedata_history(
        ["GOLDBEES"], duration="10 Y", bar_size="EOD", sleep_time=0.1)[0]

    df_equity = process_portfolio_prod(ticker_df, td_equity, 75)
    df_gold   = process_portfolio_prod(gold_df,   td_gold,   25)

    final_df = (pd.concat([df_equity, df_gold], ignore_index=True)
                .sort_values(["Date", "Ticker"]).reset_index(drop=True))

    os.makedirs(output_folder, exist_ok=True)
    middle   = os.path.basename(os.path.dirname(input_file))
    out_file = os.path.join(output_folder,
                            f"{middle}_gold_buy&hold_returns.xlsx")
    final_df.to_excel(out_file, index=False)
    print(f"✅ Prod output: {out_file}")
    return final_df


def run_part5():
    """Entry point for PART 5 – Momentum Prod / Maxfolio."""
    print("\n" + "="*70)
    print("PART 5 – MOMENTUM PROD  (Momentum prod from 11th Nov_march_rebalance.ipynb)")
    print("="*70)
    input_file = os.path.join(
        BASE_DIR, "Stocks",
        "Nifty_500_2025_Apr_20_stocks_results",
        "master_momentum_summary.xlsx")

    final_df = prepare_and_process_portfolio_prod(
        input_file    = input_file,
        start_date    = "2025-11-01",
        end_date      = date.today().strftime("%Y-%m-%d"),
        output_folder = TRIALS_DIR,
    )

    # Strip GOLDBEES rows after Nov-2025 (replaced by hedge book rebalancing)
    old_df = final_df[
        ~((final_df["Date"] > "2025-11-30") & (final_df["Ticker"] == "GOLDBEES"))
    ].copy()

    # Build hedge book (GOLDBEES/SILVERBEES/MOGSEC Dec-Jan, GOLDBEES/MOGSEC Feb,
    #                   GOLDBEES/LIQUIDCASE Mar onward)
    hedge_df = build_rebalanced_hedge_book(final_df)

    # Compute Buy_Value / Buy_Price / Quantity for hedge rows (matching notebook cell 15)
    if not hedge_df.empty:
        hedge_df["Buy_Value"] = hedge_df.groupby("Ticker")["Buy_Hold_Value"].transform("first")
        hedge_df["Buy_Price"] = hedge_df.groupby("Ticker")["Close"].transform("first")
        hedge_df["Quantity"]  = np.where(
            hedge_df["Buy_Price"] > 0,
            hedge_df["Buy_Value"] / hedge_df["Buy_Price"], 0.0)

    # Concatenate
    conc_df = (pd.concat([old_df, hedge_df], ignore_index=True)
               if not hedge_df.empty else old_df.copy())
    conc_df = conc_df.sort_values(["Date", "Ticker"]).reset_index(drop=True)

    # Add Asset Type labels (LIQUIDCASE classified as Debt)
    conc_df["Asset Type"] = np.where(
        conc_df["Ticker"] == "GOLDBEES",    "Gold",
        np.where(conc_df["Ticker"] == "SILVERBEES",  "Silver",
        np.where(conc_df["Ticker"].isin(["MOGSEC", "LIQUIDCASE"]), "Debt",
                 "Equities")))

    # Filter up to today
    conc_df = conc_df[conc_df["Date"] <= pd.Timestamp.today().normalize()]

    maxfolio_path = os.path.join(BASE_DIR, "Momentum_Maxfolio.xlsx")
    conc_df.to_excel(maxfolio_path, index=False)
    print(f"✅ Maxfolio saved: {maxfolio_path}")
    print("PART 5 done.")


# =============================================================================
# MAIN – Run all parts in sequence
# =============================================================================

if __name__ == "__main__":
    import sys
    # Pass part number as argument to run individually, e.g.:
    #   python may_momentum.py 1   → runs only PART 1
    #   python may_momentum.py     → runs PARTS 2-5 (daily)
    #   python may_momentum.py all → runs ALL parts

    parts_to_run = sys.argv[1] if len(sys.argv) > 1 else "daily"

    if parts_to_run == "1" or parts_to_run == "all":
        run_part1()   # Monthly – run once a month, adjust end_date

    if parts_to_run in ("2", "all", "daily"):
        run_part2()   # Daily Momentum

    if parts_to_run in ("3", "all", "daily"):
        run_part3()   # Ratios & KPIs

    if parts_to_run in ("4", "all", "daily"):
        run_part4()   # Beta (Ratios-Manan)

    if parts_to_run in ("5", "all", "daily"):
        run_part5()   # Momentum Prod / Maxfolio

    print("\n✅ All requested parts completed successfully.")
