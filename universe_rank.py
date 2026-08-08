import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os
import logging
import time
from truedata import TD_hist
import math

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_truedata_history(username, password, ticker_list, duration='1 Y', bar_size='EOD', sleep_time=0.1):
    """
    Fetches historical data from TrueData for a list of tickers.
    """
    td_hist = TD_hist(username, password)
    df_list = []
    error_list = []

    for ticker in ticker_list:
        try:
            df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)
            if df is None or df.empty:
                logging.error(f"No valid data for {ticker} (empty DataFrame)")
                error_list.append(ticker)
                continue
            
            # Check for valid date column and rename
            date_col = next((col for col in ['timestamp', 'datetime', 'date'] if col in df.columns), None)
            if not date_col:
                logging.error(f"No valid data for {ticker} (missing date column)")
                error_list.append(ticker)
                continue
                
            df['Ticker'] = ticker
            rename_dict = {date_col: 'Date', 'high': 'High', 'low': 'Low', 'close': 'Close', 'open': 'Open'}
            df = df.rename(columns=rename_dict)
            df_list.append(df[['Date', 'Ticker', 'Close', 'Open', 'High', 'Low']])
            logging.info(f"Fetched data for {ticker} ({len(df)} rows).")
            time.sleep(sleep_time)
        except Exception as e:
            logging.error(f"Failed to fetch data for {ticker}: {e}")
            error_list.append(ticker)

    final_df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
    return final_df, error_list

def generate_universe_rank(ticker_master_path, start_date, end_date, output_csv_path):
    # TrueData Credentials (inherited from common scripts in workspace)
    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")

    # 1. Load Universe
    logging.info(f"Loading tickers from {ticker_master_path}")
    if ticker_master_path.endswith('.csv'):
        tickers_df = pd.read_csv(ticker_master_path)
    else:
        tickers_df = pd.read_excel(ticker_master_path)
    
    # Ensure 'Ticker' column exists
    if 'Ticker' not in tickers_df.columns:
        if 'Symbol' in tickers_df.columns:
            tickers_df['Ticker'] = tickers_df['Symbol']
        else:
            raise KeyError("Ticker column not found in master file.")

    ticker_list = tickers_df['Ticker'].dropna().unique().tolist()
    # Remove .NS suffix if present (TrueData usually needs just the symbol)
    fetch_list = [t.replace('.NS', '') for t in ticker_list]

    # 2. Fetch Data
    # Fetch 1 year to ensure we cover the 6-month window easily
    data, errors = fetch_truedata_history(username, password, fetch_list, duration='1 Y')
    if data.empty:
        logging.error("No data fetched. Exiting.")
        return

    data['Date'] = pd.to_datetime(data['Date'])
    
    # 3. Filter for specific window
    filter_start = pd.to_datetime(start_date)
    filter_end = pd.to_datetime(end_date)
    window_data = data[(data['Date'] >= filter_start) & (data['Date'] <= filter_end)].copy()
    
    if window_data.empty:
        logging.error(f"No data found for period {start_date} to {end_date}")
        return

    # Pivot to get closing prices
    prices_all = window_data.pivot(index="Date", columns="Ticker", values="Close").sort_index()
    last_prices = window_data.sort_values('Date').groupby('Ticker')['Close'].last()

    # 4. Calculate Metrics
    logging.info("Calculating metrics...")
    
    # Monthly momentum logic (from notebook)
    # Group by Year-Month and take first/last EOD of each month
    monthclose = prices_all.groupby(prices_all.index.strftime('%Y-%m')).tail(1)
    monthstart = prices_all.groupby(prices_all.index.strftime('%Y-%m')).head(1)
    monthstart.index = monthclose.index
    monchange = (monthclose - monthstart) / monthstart
    momentum_metric = ((monchange + 1).product() - 1) * 100

    # Daily returns for Positive/Negative calculation
    daily_ret = prices_all.pct_change(fill_method=None)
    positive_pct = (daily_ret[daily_ret > 0].count() / daily_ret.count()) * 100
    negative_pct = (daily_ret[daily_ret < 0].count() / daily_ret.count()) * 100
    fip_metric = negative_pct - positive_pct # Calculate for all per user request

    # 5. Assemble Result
    result = pd.DataFrame({
        'Momentum': momentum_metric,
        'Positive': positive_pct,
        'Negative': negative_pct,
        'FIP': fip_metric,
        'Close': last_prices
    }).reset_index()

    # 6. Ranking Logic
    # Rank by Momentum (Descending)
    result['Rank_Mom'] = result['Momentum'].rank(method='min', ascending=False)
    result = result.sort_values(by='Rank_Mom')
    
    # Group Rank 1 to 100 (Groups of 5)
    # HINDCOPPER (Rank 1) -> Group 1.0
    # ASHOKLEY (Rank 6) -> Group 2.0
    result['Group_Rank_1_to_100'] = result['Rank_Mom'].apply(lambda x: math.ceil(x / 5))
    
    # Score (101 - Group Rank)
    result['Score'] = 101 - result['Group_Rank_1_to_100']

    # Final Column Reorder to match reference CSV
    output_cols = ['Ticker', 'Momentum', 'Rank_Mom', 'Group_Rank_1_to_100', 'Score', 'FIP', 'Close', 'Positive', 'Negative']
    result = result[output_cols]

    # Save to CSV
    result.to_csv(output_csv_path, index=False)
    logging.info(f"Successfully saved ranking results to {output_csv_path}")

if __name__ == "__main__":
    MASTER_PATH = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Ticker_Master.xlsx"
    START_DATE = "2025-09-01"
    END_DATE = "2026-02-28"
    OUTPUT_PATH = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\universe_ranked_results_20260228.csv"
    
    generate_universe_rank(MASTER_PATH, START_DATE, END_DATE, OUTPUT_PATH)
