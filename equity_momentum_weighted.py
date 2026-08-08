# =============================================================================
# equity_momentum_weighted.py
# Pure Equity Momentum Strategy:
# - Lookbacks: 1M (30%), 3M (20%), 6M (50%)
# - FIP Score + Momentum Rank
# - Filter: CMP < 7500 before ranking
# - Inception: 11th Nov, 2025, Start NAV = 100
# - No Hedge assets
# =============================================================================

import time
import logging
import os
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from pathlib import Path

# Require TrueData client
try:
    from truedata import TD_hist
except Exception:
    raise ImportError("TrueData client not found.")

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR   = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover"
NEW_MONTHLY_DIR = os.path.join(BASE_DIR, "new_monthly")
TRIALS_DIR      = os.path.join(BASE_DIR, "Trials")

def fetch_truedata_history(ticker_list, duration="1 Y", bar_size="EOD", sleep_time=0.1):
    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
    td_hist = TD_hist(username, password)
    df_list, error_list = [], []
    for ticker in ticker_list:
        try:
            df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)
            df["Ticker"] = ticker
            rename = {}
            for col in ["timestamp", "datetime", "date"]:
                if col in df.columns:
                    rename[col] = "Date"
                    break
            rename.update({"high": "High", "low": "Low", "close": "Close", "open": "Open"})
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
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    cols_lower = {c.lower(): c for c in df.columns}
    if "date" in cols_lower:
        df["Date"] = pd.to_datetime(df[cols_lower["date"]])
    elif "datetime" in cols_lower:
        df["Date"] = pd.to_datetime(df[cols_lower["datetime"]])
    elif "timestamp" in cols_lower:
        df["Date"] = pd.to_datetime(df[cols_lower["timestamp"]])
    
    if "close" in cols_lower:
        df["Close"] = df[cols_lower["close"]]
    elif "adj close" in cols_lower:
        df["Close"] = df[cols_lower["adj close"]]
        
    if "ticker" not in df.columns and "symbol" in cols_lower:
        df["Ticker"] = df[cols_lower["symbol"]]

    if "Date" in df.columns:
        df = df.dropna(subset=["Date"]).copy()
    keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Ticker"] if c in df.columns]
    return df[keep]

def run_momentum_strategy(universe_file, start_date, end_date, top_n, output_root):
    if universe_file.endswith(".csv"):
        stock_list = pd.read_csv(universe_file)[["Symbol", "ISIN Code"]]
    else:
        stock_list = pd.read_excel(universe_file)[["Symbol", "ISIN Code"]]

    stock_list["Ticker"] = stock_list["Symbol"]
    symbol_list  = stock_list["Symbol"].tolist()
    universe_name = Path(universe_file).stem
    output_dir   = os.path.join(output_root, f"{universe_name}_{top_n}_stocks_weighted_results")
    os.makedirs(output_dir, exist_ok=True)

    total_start = pd.to_datetime(start_date)
    total_end   = pd.to_datetime(end_date)

    print(f"\n📥 Downloading price data for {len(symbol_list)} symbols …")
    data, errors = fetch_truedata_history(symbol_list, duration="10 Y", bar_size="EOD")
    data = data[["Date", "Close", "Ticker"]]
    data.drop_duplicates(subset=["Date", "Ticker"], inplace=True)
    print("Failed tickers:", errors)
    prices_all = data.pivot(index="Date", columns="Ticker", values="Close").sort_index()

    windows = []
    cur = total_start
    while True:
        end_w = cur + relativedelta(months=6)
        if end_w > total_end:
            break
        wp = prices_all.loc[(prices_all.index >= cur) & (prices_all.index < end_w)].copy()
        if not wp.empty:
            windows.append((cur, end_w, wp))
        cur += relativedelta(months=1)
    print(f"📊 Created {len(windows)} rolling windows.")

    for start_w, end_w, prices in windows:
        suffix = f"{start_w.strftime('%Y%m%d')}_{end_w.strftime('%Y%m%d')}"
        prices.dropna(axis=1, how="all", inplace=True)
        if prices.empty:
            continue

        last_prices = prices.iloc[-1]
        m6_start_prices = prices.iloc[0]
        
        m3_start_date = end_w - relativedelta(months=3)
        m3_prices_df = prices.loc[prices.index >= m3_start_date]
        m3_start_prices = m3_prices_df.iloc[0] if not m3_prices_df.empty else m6_start_prices
        
        m1_start_date = end_w - relativedelta(months=1)
        m1_prices_df = prices.loc[prices.index >= m1_start_date]
        m1_start_prices = m1_prices_df.iloc[0] if not m1_prices_df.empty else m3_start_prices
        
        ret_1m = (last_prices - m1_start_prices) / m1_start_prices
        ret_3m = (last_prices - m3_start_prices) / m3_start_prices
        ret_6m = (last_prices - m6_start_prices) / m6_start_prices
        
        weighted_mom = (ret_1m * 0.30) + (ret_3m * 0.20) + (ret_6m * 0.50)
        mom = weighted_mom * 100

        daily_ret = prices.pct_change()
        positivechange = (daily_ret[daily_ret > 0].count() / daily_ret.count()) * 100
        negativechange = (daily_ret[daily_ret < 0].count() / daily_ret.count()) * 100

        result = pd.concat([positivechange, negativechange, mom], axis=1, join="inner")
        result.columns = ["Positive", "Negative", "Momentum"]
        result = result.reset_index().rename(columns={"index": "Ticker"})
        result = pd.merge(result, stock_list[["Ticker", "ISIN Code"]], on="Ticker", how="left")

        df = result.copy()

        # CMP strict filter before ranking
        df["CMP"] = df["Ticker"].map(last_prices.to_dict())
        excluded = df[df["CMP"] >= 7500]["Ticker"].tolist()
        if excluded:
            print(f"⚠️ Excluded (CMP ≥ ₹7500) before ranking: {len(excluded)} stocks")
        df = df[df["CMP"] < 7500].copy()

        df["Rank_Mom"] = df["Momentum"].rank(method="min", ascending=False)
        df["FIP"] = df.apply(lambda r: r["Negative"] - r["Positive"] if r["Momentum"] > 0 else np.nan, axis=1)
        df.dropna(subset=["FIP"], inplace=True)
        df["FIP_rank"] = df["FIP"].rank(method="first", ascending=True)
        
        # 50% / 50% Combined Rank weighting
        df["Combined_Score"] = (0.5 * df["Rank_Mom"]) + (0.5 * df["FIP_rank"])
        df["Final_Rank"] = df["Combined_Score"].rank(method="min", ascending=True)
        df = df.sort_values("Final_Rank", ascending=True)

        if end_w.strftime("%Y-%m-%d") == "2026-01-01":
            df = df[~df["Ticker"].isin(["MARUTI", "PTCIL"])]

        df = df.head(top_n)

        df["Real_Rank"] = range(1, len(df) + 1)
        df["End_Date"]  = end_w.strftime("%Y-%m-%d")
        df.to_excel(os.path.join(output_dir, f"momentum_{suffix}.xlsx"), index=False)
        print(f"✅ Window {start_w.date()} → {end_w.date()} saved.")

    # Master summary
    master_data = []
    for f in os.listdir(output_dir):
        if f.startswith("momentum_") and f.endswith(".xlsx"):
            tmp = pd.read_excel(os.path.join(output_dir, f))
            master_data.append(tmp[["End_Date", "ISIN Code", "Ticker", "Real_Rank"]])
    if master_data:
        master_df = pd.concat(master_data, ignore_index=True)
        master_path = os.path.join(output_dir, "master_momentum_summary_weighted.xlsx")
        master_df.to_excel(master_path, index=False)
        print(f"✅ Master file: {master_path}")
        return master_path
    return None

def process_portfolio_daily_equity(nav_df, ticker_data, initial_value=100, inception_date="2025-11-11"):
    df_lis = []
    last_month_value = {}
    last_month_quantity = {}

    nav_df = nav_df.sort_values(["Date", "Ticker"]).copy()
    nav_df["Date"] = pd.to_datetime(nav_df["Date"])
    ticker_data = ticker_data.sort_values(["Ticker", "Date"]).copy()
    ticker_data["Date"] = pd.to_datetime(ticker_data["Date"])
    inception_date = pd.to_datetime(inception_date)

    for year_month in nav_df["Year-Month"].drop_duplicates():
        month_nav = nav_df[nav_df["Year-Month"] == year_month].copy()
        tickers = month_nav["Ticker"].dropna().unique().tolist()
        selection_date = pd.to_datetime(month_nav["Date"].min())
        ym_date = pd.to_datetime(f"{year_month}-01")

        prev_start = ym_date - relativedelta(months=2)
        curr_start = ym_date
        curr_end = ym_date + pd.offsets.MonthEnd(0)

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
            stock_allocations = {t: last_month_value[t] for t in tickers if t in last_month_value}
            dropped = [t for t in last_month_value if t not in tickers]
            dropped_val = sum(last_month_value[t] for t in dropped)
            new_stocks = [t for t in tickers if t not in last_month_value]
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
            stock_data_flt.loc[idx, "Selection_Date"] = selection_date
            stock_data_flt.loc[idx, "Buy_Hold_Value"] = init_val * (
                (1 + stock_data_flt.loc[idx, "%change"].fillna(0)).cumprod()
            )
            buy_price = float(tkr.iloc[0]["Close"])
            quantity = last_month_quantity.get(ticker, init_val / buy_price if buy_price else 0.0)
            stock_data_flt.loc[idx, "Buy_Price"] = buy_price
            stock_data_flt.loc[idx, "Quantity"] = quantity
            if "Real_Rank" in month_nav.columns:
                rr = month_nav.loc[month_nav["Ticker"] == ticker, "Real_Rank"]
                if not rr.empty:
                    stock_data_flt.loc[idx, "Real_Rank"] = rr.iloc[0]

        last_month_quantity = stock_data_flt.groupby("Ticker")["Quantity"].last().to_dict()
        last_month_value = stock_data_flt.groupby("Ticker")["Buy_Hold_Value"].last().to_dict()
        stock_data_flt["Total_Portfolio_Value"] = stock_data_flt.groupby("Date")["Buy_Hold_Value"].transform("sum")
        df_lis.append(stock_data_flt)

    if not df_lis:
        return pd.DataFrame()
    final_df = pd.concat(df_lis, ignore_index=True).sort_values(["Date", "Ticker"]).reset_index(drop=True)
    return final_df

def run_part1():
    print("\n" + "="*70)
    print("PART 1 – WEIGHTED MONTHLY MOMENTUM")
    print("="*70)
    master = run_momentum_strategy(
        universe_file=os.path.join(NEW_MONTHLY_DIR, "ticker_master_may26.xlsx"),
        start_date="2022-06-01",
        end_date="2026-05-01",
        top_n=20,
        output_root=NEW_MONTHLY_DIR,
    )
    print("Master summary:", master)
    return master

def run_part2(input_file):
    print("\n" + "="*70)
    print("PART 2 – PURE EQUITY DAILY MOMENTUM (Inception: 2025-11-11)")
    print("="*70)
    
    start_date = "2025-11-11"
    end_date = date.today().strftime("%Y-%m-%d")

    nav_raw = pd.read_excel(input_file).rename(columns={"End_Date": "Date"})
    nav_raw["Date"] = pd.to_datetime(nav_raw["Date"])
    
    nav_df = nav_raw[(nav_raw["Date"] >= "2025-11-01") & (nav_raw["Date"] <= end_date)].copy()
    nav_df["Year-Month"] = nav_df["Date"].dt.to_period("M").astype(str)

    unique_tickers = nav_df["Ticker"].unique().tolist()
    if not unique_tickers:
        print("No tickers found for the backtest period!")
        return

    print(f"📥 Fetching TrueData for {len(unique_tickers)} equity tickers...")
    td_equity, errs = fetch_truedata_history(unique_tickers, duration="2 Y", bar_size="EOD", sleep_time=0.1)
    td_equity = _sanitize_price_df(td_equity)

    if td_equity.empty:
        print("❌ No equity price data fetched. Exiting.")
        return

    final_df = process_portfolio_daily_equity(
        nav_df=nav_df, 
        ticker_data=td_equity, 
        initial_value=100, 
        inception_date=start_date
    )

    if final_df.empty:
        print("❌ Final DataFrame is empty.")
        return

    os.makedirs(TRIALS_DIR, exist_ok=True)
    out_file = os.path.join(TRIALS_DIR, "Equity_Weighted_buy&hold_returns.xlsx")
    final_df.to_excel(out_file, index=False)
    print(f"✅ Daily output saved to: {out_file}")

    # Generate the NAV Day-on-Day CSV
    nav_daily = final_df.drop_duplicates(subset=["Date"])[["Date", "Total_Portfolio_Value"]].copy()
    nav_daily = nav_daily.sort_values("Date")
    
    # Rename Total_Portfolio_Value to NAV
    nav_daily.rename(columns={"Total_Portfolio_Value": "NAV"}, inplace=True)
    nav_daily["DoD_Pct_Change"] = nav_daily["NAV"].pct_change() * 100
    
    nav_output = nav_daily[["Date", "NAV", "DoD_Pct_Change"]]
    nav_csv_path = os.path.join(TRIALS_DIR, "Equity_NAV_DoD_Changes.csv")
    nav_output.to_csv(nav_csv_path, index=False)
    print(f"✅ NAV DoD Changes saved to: {nav_csv_path}")

if __name__ == "__main__":
    import sys
    parts_to_run = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    master_file = os.path.join(
        NEW_MONTHLY_DIR, 
        "ticker_master_may26_20_stocks_weighted_results", 
        "master_momentum_summary_weighted.xlsx"
    )

    if parts_to_run in ("1", "all"):
        master_file = run_part1()

    if parts_to_run in ("2", "all"):
        if master_file and os.path.exists(master_file):
            run_part2(master_file)
        else:
            print("Master file not found. Please run part 1 first.")
