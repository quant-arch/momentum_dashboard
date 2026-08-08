import time
import logging
import pandas as pd
from truedata import TD_hist

def fetch_truedata_history(
    username: str,
    password: str,
    ticker_list: list,
    duration: str = '1 Y',
    bar_size: str = 'EOD',
    sleep_time: float = 0.1
) -> tuple[pd.DataFrame, list]:
    """
    Fetches historical data from TrueData for a list of tickers.

    Parameters
    ----------
    username : str
        TrueData username.
    password : str
        TrueData password.
    ticker_list : list
        List of ticker symbols to fetch data for.
    duration : str, optional
        Duration of data (e.g., '1 Y', '25 Y', etc.). Default is '1 Y'.
    bar_size : str, optional
        Bar size for data ('EOD', 'WEEK', etc.). Default is 'EOD'.
    sleep_time : float, optional
        Delay between API calls to avoid throttling. Default is 0.2 seconds.

    Returns
    -------
    final_df : pd.DataFrame
        Combined DataFrame of all tickers' historical data.
    error_list : list
        List of tickers that failed to fetch.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Initialize connection
    td_hist = TD_hist(username, password)

    df_list = []
    error_list = []

    for ticker in ticker_list:
        try:
            df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)

            df['Ticker'] = ticker
            df = df.rename(columns={
                'timestamp': 'Date',
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'open': 'Open'
            })

            df_list.append(df)
            logging.info(f"Fetched data for {ticker} ({len(df)} rows).")
            time.sleep(sleep_time)

        except Exception as e:
            logging.error(f"Failed to fetch data for {ticker}: {e}")
            error_list.append(ticker)

    final_df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
    return final_df, error_list

import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import yfinance as yf
from pathlib import Path

import os

def run_momentum_strategy(universe_file: str,
                          start_date: str,
                          end_date: str,
                          top_n: int,
                          output_root: str = "Momentum_Results",
                          freeze_cutoff_date: str = "2026-05-31",
                          output_dir_override: str = None) -> str:
    """
    Run rolling-window momentum strategy on given stock universe.

    Parameters
    ----------
    universe_file : str
        Path to universe file (.csv or .xlsx) with columns ["Symbol", "ISIN Code"].
    start_date : str
        Start date for backtest (YYYY-MM-DD).
    end_date : str
        End date for backtest (YYYY-MM-DD).
    top_n : int
        Number of top ranked stocks to select each window.
    output_root : str
        Root folder where results will be saved.
    freeze_cutoff_date : str
        Date (YYYY-MM-DD) up to which existing window files will not be overwritten.
    output_dir_override : str or None
        If provided, use this exact directory to store window files instead of
        the default `<output_root>/<universe_name>_{top_n}_stocks_results`.

    Returns
    -------
    str
        Path to master summary file.
    """


    # ==== 1. Load Universe ====
    if universe_file.endswith(".csv"):
        stock_list = pd.read_csv(universe_file)[["Symbol", "ISIN Code"]]
    else:
        stock_list = pd.read_excel(universe_file)[["Symbol", "ISIN Code"]]
    # username = os.getenv("TRUEDATA_USERNAME")
    # password = os.getenv("TRUEDATA_PASSWORD")
    
    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
    # username = 'td105'
    # password = os.getenv("TRUEDATA_PASSWORD")
    # stock_list["Ticker"] = stock_list["Symbol"] + ".NS"
    stock_list["Ticker"] = stock_list["Symbol"].astype(str).str.strip().str.upper()
    banned_tickers = {"APARINDS"}
    stock_list = stock_list[~stock_list["Ticker"].isin(banned_tickers)].copy()
    symbol_list = stock_list["Ticker"].tolist()
    universe_name = Path(universe_file).stem

    # Determine output directory (allow override)
    if output_dir_override:
        output_dir = output_dir_override
    else:
        output_dir = os.path.join(output_root, f"{universe_name}_{top_n}_stocks_results")
    os.makedirs(output_dir, exist_ok=True)

    # ==== 2. Download Data ====
    total_start = pd.to_datetime(start_date)
    total_end = pd.to_datetime(end_date)

    print(f"\n📥 Downloading price data for {len(symbol_list)} symbols...")
    # data = yf.download(symbol_list, start=total_start.strftime('%Y-%m-%d'),
    #                    end=total_end.strftime('%Y-%m-%d'), progress=True)
    # prices_all = data["Close"]
    # prices_all.index = pd.to_datetime(prices_all.index)
    # print("✅ Download complete.")
    data, errors = fetch_truedata_history(username, password, symbol_list, duration='10 Y', bar_size='EOD')
    data['Ticker'] = data['Ticker'].astype(str).str.strip().str.upper()
    data = data[['Date', 'Close', 'Ticker']]
    data.drop_duplicates(subset=['Date', 'Ticker'], inplace=True)
    print(data)
    print("Failed tickers:", errors)
    prices = data.pivot(index="Date", columns="Ticker", values="Close")
    # optional: sort by date
    prices_all = prices.sort_index()


    # ==== 3. Create Rolling Windows ====
    windows = []
    current_start = total_start
    while True:
        current_end = current_start + relativedelta(months=6)
        if current_end > total_end:
            break
        window_prices = prices_all.loc[(prices_all.index >= current_start) & (prices_all.index < current_end)].copy()
        if not window_prices.empty:
            windows.append((current_start, current_end, window_prices))
        current_start += relativedelta(months=1)

    print(f"📊 Created {len(windows)} rolling windows.")

    # ==== 4. Process Each Window ====
    for start, end, prices in windows:
        file_suffix = f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}" 
        print(f"\n🔍 Processing window: {start.date()} → {end.date()}")

        prices.dropna(axis=1, how='all', inplace=True)
        if prices.empty:
            print("⚠️ All price data missing. Skipping window.")
            continue

        # Monthly momentum
        monthclose = prices.groupby(prices.index.strftime('%Y-%m')).tail(1)
        monthstart = prices.groupby(prices.index.strftime('%Y-%m')).head(1)
        monthstart.index = monthclose.index
        monchange = (monthclose - monthstart) / monthstart
        MOM = (monchange + 1).product() - 1
        mom = MOM * 100

        # Daily returns
        daily_ret = prices.pct_change(fill_method=None)
        positivechange = (daily_ret[daily_ret > 0].count() / daily_ret.count()) * 100
        negativechange = (daily_ret[daily_ret < 0].count() / daily_ret.count()) * 100

        result = pd.concat([positivechange, negativechange, mom], axis=1, join='inner')
        result.columns = ["Positive", "Negative", "Momentum"]
        result = result.reset_index().rename(columns={'index': 'Ticker'})
        try:
            last_prices = prices.tail(1).iloc[0].to_dict()
            last_prices = {str(k).strip().upper(): v for k, v in last_prices.items()}
        except Exception:
            last_prices = {}
        result["Last_Price"] = result["Ticker"].map(last_prices)
        pre_count = len(result)
        result = result[result["Last_Price"].isna() | (result["Last_Price"] <= 7500)]
        removed_count = pre_count - len(result)
        if removed_count:
            print(f"🔒 Excluded {removed_count} stocks with Last_Price > 7500 from this window")

        # Merge ISIN
        result = pd.merge(result, stock_list[["Ticker", "ISIN Code"]], on="Ticker", how="left")

        # Ranking
        df = result.copy()
        df["Rank_Mom"] = df["Momentum"].rank(method='min', ascending=False)
        print('rank df:', df)
        df['FIP'] = df.apply(lambda row: row['Negative'] - row['Positive'] if row['Momentum'] > 0 else np.nan, axis=1)
        # df['FIP'] = df.apply(lambda row: row['Negative'] - row['Positive'])

        df.dropna(inplace=True)
        df["FIP_rank"] = df["FIP"].rank(method="first", ascending=True)
        df["Combined_Rank"] = df["Rank_Mom"] + df["FIP_rank"]
        if end.strftime('%Y-%m-%d') == '2026-01-01':
            df = df[~(df['Ticker'].isin(['MARUTI', 'PTCIL']))]

        df = df.sort_values(by="Combined_Rank", ascending=True).head(top_n)
        df["Real_Rank"] = range(1, len(df) + 1)
        df["End_Date"] = end.strftime('%Y-%m-%d')


        # Save each window
        output_file = os.path.join(output_dir, f"momentum_{file_suffix}.xlsx")

        # Determine freeze behavior: do not overwrite existing files
        # for windows whose end date is on or before `freeze_cutoff_date`.
        try:
            freeze_cutoff = pd.to_datetime(freeze_cutoff_date).date() if freeze_cutoff_date else None
        except Exception:
            freeze_cutoff = None

        window_end_date = pd.to_datetime(end).date()

        if freeze_cutoff is not None and window_end_date <= freeze_cutoff and os.path.exists(output_file):
            print(f"⏸ Skipping overwrite of frozen window: {file_suffix} (<= {freeze_cutoff})")
        else:
            df.to_excel(output_file, index=False)
            print(f"✅ Saved results to: {output_file}")

    # ==== 5. Master File ====
    print("\n📂 Creating master summary file...")
    master_data = []
    for file in os.listdir(output_dir):
        if file.startswith("momentum_") and file.endswith(".xlsx"):
            df = pd.read_excel(os.path.join(output_dir, file))
            selected_df = df[["End_Date", "ISIN Code", "Ticker", 'Real_Rank']].copy()

            master_data.append(selected_df)

    if not master_data:
        print("⚠️ No window files found, master not created.")
        return None

    master_df = pd.concat(master_data, ignore_index=True)
    master_file_path = os.path.join(output_dir, "master_momentum_summary.xlsx")
    master_df.to_excel(master_file_path, index=False)
    print(f"✅ Master file saved to: {master_file_path}")
    return master_file_path


# Momentum/Automating Momentum/Universe/Nifty_500_2025_Apr.csv
# "C:\Users\Admin\Momentum\Automating Momentum\Universe\Nifty_500_2025_Apr.csv"
master_file = run_momentum_strategy(
    universe_file=r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Universe\ticker_master_may26.xlsx",
    start_date="2022-06-01",
    end_date="2026-06-01",
    top_n=20,
    output_root="Stocks_old",
    # override to append new windows into the existing Nifty_500_2025_Apr output folder
    output_dir_override=r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results"
)
print("Master summary located at:", master_file)

# ----------------xxxxxxxxxxxxxxx---------------------------------------