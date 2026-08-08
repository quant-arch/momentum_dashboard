import sys
import os
import pandas as pd
from datetime import datetime
import logging
import yfinance as yf

if not hasattr(pd.DataFrame, "timestamp"):
    def _get_df_timestamp(self):
        return self["timestamp"] if "timestamp" in self.columns else None
    def _set_df_timestamp(self, value):
        self["timestamp"] = value
    pd.DataFrame.timestamp = property(_get_df_timestamp, _set_df_timestamp)

SCRIPT_DIR = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2"
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj, resilient_fetch

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def fetch_from_yfinance(ticker, start_date, end_date):
    print(f"Attempting to fetch {ticker} from yfinance as fallback...")
    try:
        data = yf.download(ticker, start=start_date, end=end_date)
        if data is not None and not data.empty:
            data = data.reset_index()
            # Normalize columns
            data.columns = [c[0].title() if isinstance(c, tuple) else c.title() for c in data.columns]
            rename_map = {'Datetime': 'Date'}
            data = data.rename(columns=rename_map)
            # Ensure proper case for OHLC
            for col in ['Open', 'High', 'Low', 'Close']:
                if col.lower() in [c.lower() for c in data.columns]:
                    actual_col = [c for c in data.columns if c.lower() == col.lower()][0]
                    data = data.rename(columns={actual_col: col})
            return data
    except Exception as e:
        print(f"yfinance fetch failed: {e}")
    return None

def main():
    HYBRID_INDEX_SYMBOL = "^NIFTY6535" 
    
    # We will fetch data from 10 years ago to today
    start_date = datetime(2014, 1, 1)
    end_date = datetime.now()
    
    print(f"Attempting to fetch data for {HYBRID_INDEX_SYMBOL} from TrueData...")
    td_obj = get_td_obj()
    df = resilient_fetch(td_obj, HYBRID_INDEX_SYMBOL, start_date, end_date)
    
    if df is None or df.empty:
        print(f"TrueData fetch failed or returned no data for {HYBRID_INDEX_SYMBOL}.")
        df = fetch_from_yfinance(HYBRID_INDEX_SYMBOL, start_date, end_date)
        
    if df is not None and not df.empty:
        output_file = os.path.join(SCRIPT_DIR, "Hybrid_Index_Data.csv")
        df.to_csv(output_file, index=False)
        print(f"\nSuccessfully fetched {len(df)} rows of data.")
        print(f"Data saved to: {output_file}")
        print(df.head())
    else:
        print(f"\nFailed to fetch data for {HYBRID_INDEX_SYMBOL} from both TrueData and yfinance.")

if __name__ == "__main__":
    main()
