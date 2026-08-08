import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os

# Monkey-patch pd.DataFrame to add 'timestamp' property for truedata (pandas 3.0 compatibility)
if not hasattr(pd.DataFrame, 'timestamp'):
    def get_df_timestamp(self):
        return self['timestamp'] if 'timestamp' in self.columns else None
    def set_df_timestamp(self, value):
        self['timestamp'] = value
    pd.DataFrame.timestamp = property(get_df_timestamp, set_df_timestamp)

# Import your TrueData fetch function (from notebook)
from truedata import TD_hist

def fetch_truedata_history(username, password, ticker_list, duration='6 M', bar_size='EOD', sleep_time=0.1):
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
    import time
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Initialize connection
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
            # Check for any valid date column
            date_col = None
            for col in ['timestamp', 'datetime', 'date']:
                if col in df.columns:
                    date_col = col
                    break
            if not date_col:
                logging.error(f"No valid data for {ticker} (missing date column)")
                error_list.append(ticker)
                continue
            df['Ticker'] = ticker
            rename_dict = {date_col: 'Date', 'high': 'High', 'low': 'Low', 'close': 'Close', 'open': 'Open'}
            df = df.rename(columns=rename_dict)
            df_list.append(df)
            logging.info(f"Fetched data for {ticker} ({len(df)} rows).")
            time.sleep(sleep_time)
        except Exception as e:
            logging.error(f"Failed to fetch data for {ticker}: {e}")
            error_list.append(ticker)

    final_df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
    return final_df, error_list

def rank_tickers(ticker_master_path, username, password, output_path, start_date=None, end_date=None):
    # Load tickers
    tickers_df = pd.read_excel(ticker_master_path)
    # Strip .NS if present, as TrueData REST API usually expects just the symbol
    ticker_list = [t.replace('.NS', '') for t in tickers_df['Ticker'].tolist()]

    # Fetch past 1 year data to cover custom ranges
    data, errors = fetch_truedata_history(username, password, ticker_list, duration='1 Y', bar_size='EOD')
    data = data[['Date', 'Close', 'Ticker']]
    data.drop_duplicates(subset=['Date', 'Ticker'], inplace=True)
    prices = data.pivot(index="Date", columns="Ticker", values="Close")
    prices_all = prices.sort_index()

    # Define window range
    if start_date and end_date:
        total_start = pd.to_datetime(start_date)
        total_end = pd.to_datetime(end_date)
    else:
        # Default to last 6 months
        total_end = pd.to_datetime(prices_all.index.max())
        total_start = total_end - relativedelta(months=6)

    window_prices = prices_all.loc[(prices_all.index >= total_start) & (prices_all.index <= total_end)].copy()
    
    if window_prices.empty:
        print(f"Warning: No data found for specified range: {total_start} to {total_end}")
        return

    # Monthly momentum
    monthclose = window_prices.groupby(window_prices.index.strftime('%Y-%m')).tail(1)
    monthstart = window_prices.groupby(window_prices.index.strftime('%Y-%m')).head(1)
    monthstart.index = monthclose.index
    monchange = (monthclose - monthstart) / monthstart
    MOM = (monchange + 1).product() - 1
    mom = MOM * 100

    # Daily returns
    daily_ret = window_prices.pct_change(fill_method=None)
    positivechange = (daily_ret[daily_ret > 0].count() / daily_ret.count()) * 100
    negativechange = (daily_ret[daily_ret < 0].count() / daily_ret.count()) * 100

    result = pd.concat([positivechange, negativechange, mom], axis=1, join='inner')
    result.columns = ["Positive", "Negative", "Momentum"]
    result = result.reset_index().rename(columns={'index': 'Ticker'})

    # Ranking (Matching Momentum Stocks Monthly.ipynb logic)
    df = result.copy()
    # 1. Rank Momentum (highest is best, so ascending=False)
    df["Rank_Mom"] = df["Momentum"].rank(method='min', ascending=False)
    
    # 2. Calculate FIP and Rank it (lowest is best, so ascending=True)
    df["FIP"] = df.apply(lambda row: row['Negative'] - row['Positive'] if row['Momentum'] > 0 else np.nan, axis=1)
    df.dropna(subset=['FIP'], inplace=True)
    df["FIP_Rank"] = df["FIP"].rank(method="first", ascending=True)
    
    # 3. Combine Ranks (lower sum is better)
    df["Combined_Rank"] = df["Rank_Mom"] + df["FIP_Rank"]
    df = df.sort_values(by="Combined_Rank", ascending=True)
    
    # 4. Final Rank
    df["Final_Rank"] = range(1, len(df) + 1)
    df["End_Date"] = total_end.strftime('%Y-%m-%d')

    # Select and reorder columns for output
    output_cols = ["Ticker", "Momentum", "FIP", "Rank_Mom", "FIP_Rank", "Combined_Rank", "Final_Rank", "End_Date"]
    df_out = df[output_cols]
    df_out.to_excel(output_path, index=False)
    print(f"Ranking complete for period {total_start.date()} to {total_end.date()}. Results saved to: {output_path}")

# Example usage:
if __name__ == "__main__":
    rank_tickers(
        ticker_master_path=r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Ticker_Master.xlsx",
        username=os.getenv("TRUEDATA_USERNAME"),  # Replace with your TrueData username
        password=os.getenv("TRUEDATA_PASSWORD"), # Replace with your TrueData password
        output_path=r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\ticker_rank_results.xlsx",
        start_date="2025-09-01",
        end_date="2026-02-28"
    )
