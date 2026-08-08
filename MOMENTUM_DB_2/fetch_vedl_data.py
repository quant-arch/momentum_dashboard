import sys
import pandas as pd
from datetime import datetime

# Insert the path to truedata_connector
sys.path.insert(0, r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2")
from truedata_connector import get_td_obj

def main():
    td_hist = get_td_obj()
    ticker = 'VEDL'
    
    print(f"Fetching data for {ticker}...")
    # Fetch 1 year of EOD data to ensure we cover Jan 1, 2026 to June 25, 2026
    df = td_hist.get_historic_data([ticker], duration='1 Y', bar_size='EOD')
    
    if df is None or (hasattr(df, 'empty') and df.empty):
        print(f"No data fetched for {ticker}")
        return
        
    # Standardize column names based on the reference script
    rename_dict = {}
    if 'timestamp' in df.columns:
        rename_dict['timestamp'] = 'Date'
    elif 'datetime' in df.columns:
        rename_dict['datetime'] = 'Date'
    elif 'date' in df.columns:
        rename_dict['date'] = 'Date'
    rename_dict.update({
        'high': 'High', 'low': 'Low',
        'close': 'Close', 'open': 'Open'
    })
    df = df.rename(columns=rename_dict)
    
    # Convert Date to datetime and filter for our date range
    df['Date'] = pd.to_datetime(df['Date'])
    
    start_date = pd.to_datetime('2026-01-01')
    end_date = pd.to_datetime('2026-06-25')
    
    filtered_df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)].copy()
    
    # Keep only Date and Close (c) prices
    filtered_df = filtered_df[['Date', 'Close']].reset_index(drop=True)
    
    print(f"\nClosing prices for {ticker} from {start_date.date()} to {end_date.date()}:")
    print(filtered_df.to_string())
    
    # Optionally save to a CSV
    output_path = f"{ticker}_close_prices.csv"
    filtered_df.to_csv(output_path, index=False)
    print(f"\nData successfully saved to {output_path}")

if __name__ == '__main__':
    main()
