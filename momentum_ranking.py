import time
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
import os
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

def run_momentum_strategy(universe_file: str,
                          start_date: str,
                          end_date: str,
                          top_n: int,
                          output_root: str = "Momentum_Results",
                          preserve_until: str | None = None) -> str:
    """
    Run rolling-window momentum strategy on given stock universe.
    """

    # ==== 1. Load Universe ====
    if universe_file.endswith(".csv"):
        stock_list = pd.read_csv(universe_file)[["Symbol", "ISIN Code"]]
    else:
        stock_list = pd.read_excel(universe_file)[["Symbol", "ISIN Code"]]

    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
    stock_list["Ticker"] = stock_list["Symbol"] 
    stock_list["Ticker"] = stock_list["Ticker"].astype(str).str.strip().str.upper()

    # Permanently ban specific tickers from the portfolio universe before fetching data
    banned_tickers = {"APARINDS"}
    stock_list = stock_list[~stock_list["Ticker"].isin(banned_tickers)].copy()

    symbol_list = stock_list["Ticker"].tolist()
    universe_name = Path(universe_file).stem
    output_dir = os.path.join(output_root, f"{universe_name}_{top_n}_stocks_results")
    os.makedirs(output_dir, exist_ok=True)

    if preserve_until is None and universe_name == 'Nifty_500_2025_Apr' and top_n == 20:
        preserve_until = "2026-04-30"
        print(f"🔒 Freezing data up to {preserve_until} for {universe_name}_{top_n}_stocks_results")

    # ==== 2. Download Data ====
    total_start = pd.to_datetime(start_date)
    total_end = pd.to_datetime(end_date)

    print(f"\n📥 Downloading price data for {len(symbol_list)} symbols...")
    data, errors = fetch_truedata_history(username, password, symbol_list, duration='10 Y', bar_size='EOD')
    data = data[['Date', 'Close', 'Ticker']]
    data.drop_duplicates(subset=['Date', 'Ticker'], inplace=True)

    data['Ticker'] = data['Ticker'].astype(str).str.strip().str.upper()
    prices = data.pivot(index="Date", columns="Ticker", values="Close")
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
    preserve_dt = pd.to_datetime(preserve_until) if preserve_until else None
    for start, end, prices in windows:
        file_suffix = f"{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}"
        print(f"\n🔍 Processing window: {start.date()} → {end.date()}")

        if preserve_dt is not None and end <= preserve_dt:
            print(f"⏭️ Skipping preserved window ending {end.date()} (preserve_until={preserve_dt.date()}).")
            continue

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

        result['Ticker'] = result['Ticker'].astype(str).str.strip().str.upper()
        result = pd.merge(result, stock_list[["Ticker", "ISIN Code"]], on="Ticker", how="left")

        try:
            last_prices = prices.tail(1).iloc[0].to_dict()
            last_prices = {str(k).strip().upper(): v for k, v in last_prices.items()}
        except Exception:
            last_prices = {}
        result['Last_Price'] = result['Ticker'].map(last_prices)

        # Removed filter: result['Last_Price'] <= 7500
        # pre_count = len(result)
        # result = result[result['Last_Price'].isna() | (result['Last_Price'] <= 7500)]
        # removed_count = pre_count - len(result)
        # if removed_count:
        #     print(f"🔒 Excluded {removed_count} stocks with Last_Price > 7500 from this window")

        df = result.copy()
        df["Rank_Mom"] = df["Momentum"].rank(method='min', ascending=False)
        
        # Filter stocks where past 6 months returns are negative or 0
        # This is handled by the FIP calculation where momentum > 0
        df['FIP'] = df.apply(lambda row: row['Negative'] - row['Positive'] if row['Momentum'] > 0 else np.nan, axis=1)

        # Removed the filter where past 6 months returns are negative or 0
        # The original code used df.dropna(inplace=True) after FIP calculation which effectively removes momentum <= 0
        # To "not consider filtering stocks where past 6 months returns are negative or 0", we should allow FIP to be calculated for all.
        df['FIP'] = df.apply(lambda row: row['Negative'] - row['Positive'], axis=1)

        # df.dropna(inplace=True) # Removed dropna to keep all stocks
        df["FIP_rank"] = df["FIP"].rank(method="first", ascending=True)
        df["Combined_Rank"] = df["Rank_Mom"] + df["FIP_rank"]
        
        if end.strftime('%Y-%m-%d') == '2026-01-01':
            df = df[~(df['Ticker'].isin(['MARUTI', 'PTCIL']))]

        # Ranking all the universe - we sort everything and then take top_n if required, or keep all.
        # The user said "rank all the universe", which usually means they want the full ranked list.
        # But top_n is still a parameter. I will keep sorting but maybe output everything if top_n is large.
        df = df.sort_values(by="Combined_Rank", ascending=True)
        # If the user wants to rank "all", they might still want a head(top_n) for the Excel files, 
        # or they might want the full list. Given the request, I'll keep top_n but it can be set to len(df).
        
        # Taking top_n as per original logic, but user can pass a very large top_n to get "all".
        # Actually, "rank all the universe" suggests they want the full list.
        # I'll modify the call to use a large top_n or just remove .head(top_n) here.
        # Let's keep .head(top_n) but allow it to be large.
        df_top = df.head(top_n)
        df_top["Real_Rank"] = range(1, len(df_top) + 1)
        df_top["End_Date"] = end.strftime('%Y-%m-%d')

        # Manual override: for May 2026 windows, replace ADANIENSOL -> VEDL (keep backups elsewhere)
        try:
            if getattr(end, 'year', None) == 2026 and getattr(end, 'month', None) == 5 and 'ADANIENSOL' in df_top['Ticker'].astype(str).str.upper().values:
                print(f"🔁 Replacing ADANIENSOL with VEDL for window ending {end.date()}")
                df_top.loc[df_top['Ticker'].astype(str).str.upper() == 'ADANIENSOL', 'Ticker'] = 'VEDL'
                if 'ISIN Code' in df_top.columns:
                    df_top.loc[df_top['Ticker'] == 'VEDL', 'ISIN Code'] = 'INE205A01025'
        except Exception:
            pass

        # Prevent duplicate tickers (e.g., VEDL introduced twice after replacement)
        try:
            dup_count = df_top['Ticker'].duplicated().sum()
            if dup_count > 0:
                print(f"⚠️ Removing {dup_count} duplicate ticker(s) in this window (keeping first occurrence)")
                df_top = df_top.drop_duplicates(subset=['Ticker'], keep='first')
                # re-sort and re-rank after dedupe
                df_top = df_top.sort_values(by="Combined_Rank", ascending=True).head(top_n)
                df_top["Real_Rank"] = range(1, len(df_top) + 1)
        except Exception:
            pass

        # Save each window (overwrite only for non-preserved windows)
        output_file = os.path.join(output_dir, f"momentum_{file_suffix}.xlsx")
        df_top.to_excel(output_file, index=False)
        print(f"✅ Saved results to: {output_file}")

    # ==== 5. Master File ====
    print("\n📂 Creating master summary file...")
    master_data = []
    for file in os.listdir(output_dir):
        if file.startswith("momentum_") and file.endswith(".xlsx"):
            df_file = pd.read_excel(os.path.join(output_dir, file))
            selected_df = df_file[["End_Date", "ISIN Code", "Ticker", 'Real_Rank']].copy()
            master_data.append(selected_df)

    if master_data:
        master_df = pd.concat(master_data, ignore_index=True)
        master_df['Ticker'] = master_df['Ticker'].astype(str).str.strip().str.upper()

        # Enforce May-2026 manual replacement in master: remove/replace ADANIENSOL rows
        try:
            end_dates = pd.to_datetime(master_df['End_Date'], errors='coerce')
            replace_mask = (end_dates.dt.year == 2026) & (end_dates.dt.month == 5) & (master_df['Ticker'] == 'ADANIENSOL')
            if replace_mask.any():
                print(f"🔁 Replacing {replace_mask.sum()} ADANIENSOL rows with VEDL in master (May 2026)")
                master_df.loc[replace_mask, 'Ticker'] = 'VEDL'
                if 'ISIN Code' in master_df.columns:
                    master_df.loc[replace_mask, 'ISIN Code'] = 'INE205A01025'
        except Exception:
            pass

        # Remove duplicate End_Date+Ticker rows in master (prevents VEDL appearing twice for same window)
        try:
            dup_master = master_df.duplicated(subset=['End_Date', 'Ticker'], keep='first').sum()
            if dup_master:
                print(f"⚠️ Removing {dup_master} duplicate End_Date+Ticker rows in master (keeping first)")
                master_df.drop_duplicates(subset=['End_Date', 'Ticker'], keep='first', inplace=True)
        except Exception:
            pass

        master_file_path = os.path.join(output_dir, "master_momentum_summary.xlsx")
        if os.path.exists(master_file_path):
            existing_master = pd.read_excel(master_file_path)
            existing_master['Ticker'] = existing_master['Ticker'].astype(str).str.strip().str.upper()
            combined = pd.concat([existing_master, master_df], ignore_index=True)
            combined.drop_duplicates(subset=['End_Date', 'ISIN Code', 'Ticker'], keep='first', inplace=True)
            combined.to_excel(master_file_path, index=False)
            print(f"✅ Master file updated (appended new rows) at: {master_file_path}")
            return master_file_path
        else:
            master_df.to_excel(master_file_path, index=False)
            print(f"✅ Master file saved to: {master_file_path}")
            return master_file_path
    else:
        print("⚠️ No window files found, master not created.")
        return None

if __name__ == "__main__":
    # Example execution based on the notebook's last cell
    # Note: top_n is set to a large number to "rank all the universe" if desired, 
    # but the notebook used 20. I'll stick to a large number or 1000 to cover the universe.
    
    universe_path = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\new_monthly\ticker_master_may26.xlsx"
    
    # Check if file exists before running
    if os.path.exists(universe_path):
        master_file = run_momentum_strategy(
            universe_file=universe_path,
            start_date="2022-06-01",
            end_date="2026-05-31",
            top_n=1000, # Large enough to include all stocks in the universe
            output_root="Stocks_Full_Rank",
            preserve_until="2026-04-30",
        )
        print("Master summary located at:", master_file)
    else:
        print(f"Universe file not found: {universe_path}")
