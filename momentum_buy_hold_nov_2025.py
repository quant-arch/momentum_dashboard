import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import yfinance as yf
# import pyodbc # Removed as unused
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import time
import logging
from truedata import TD_hist
import os

# --- Configurations ---
START_DATE = '2025-11-11'
INITIAL_NAV = 100.0
EQUITY_ALLOCATION = 75.0
HEDGE_ALLOCATION = 25.0
INPUT_FILE = "Stocks/Nifty_500_2025_Apr_20_stocks_results/master_momentum_summary.xlsx"
OUTPUT_FILE = "buy_hold_csv.csv"

# --- Functions ---

def fetch_truedata_history(
    ticker_list: list,
    duration: str = '2 Y',
    bar_size: str = 'EOD',
    sleep_time: float = 0.1
) -> tuple[pd.DataFrame, list]:
    """
    Fetches historical data from TrueData for a list of tickers.
    """
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    username = os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
    
    td_hist = TD_hist(username, password)
    df_list = []
    error_list = []
    
    for ticker in ticker_list:
        try:
            df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)
            if df is None or df.empty:
                logging.warning(f"No data for {ticker}")
                error_list.append(ticker)
                continue
                
            df['Ticker'] = ticker
            rename_dict = {}
            if 'timestamp' in df.columns:
                rename_dict['timestamp'] = 'Date'
            elif 'datetime' in df.columns:
                rename_dict['datetime'] = 'Date'
            elif 'date' in df.columns:
                rename_dict['date'] = 'Date'
            
            rename_dict.update({
                'high': 'High',
                'low': 'Low',
                'close': 'Close',
                'open': 'Open'
            })
            df = df.rename(columns=rename_dict)
            df_list.append(df)
            logging.info(f"Fetched data for {ticker} ({len(df)} rows).")
            time.sleep(sleep_time)
        except Exception as e:
            logging.error(f"Failed to fetch data for {ticker}: {e}")
            error_list.append(ticker)
            
    final_df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
    return final_df, error_list

def process_portfolio(nav_df, ticker_data, initial_value=75, inception_date=None):
    """
    Process portfolio allocation with month-by-month rebalancing.
    """
    df_lis = []
    last_month_value = {}
    last_month_quantity = {}

    nav_df = nav_df.sort_values(['Date', 'Ticker']).copy()
    nav_df['Date'] = pd.to_datetime(nav_df['Date'])
    ticker_data = ticker_data.sort_values(['Ticker', 'Date']).copy()
    ticker_data['Date'] = pd.to_datetime(ticker_data['Date'])

    if inception_date is None:
        inception_date = nav_df['Date'].min()
    else:
        inception_date = pd.to_datetime(inception_date)

    year_months = nav_df['Year-Month'].drop_duplicates()
    
    for year_month in year_months:
        month_nav = nav_df[nav_df['Year-Month'] == year_month].copy()
        tickers = month_nav['Ticker'].dropna().unique().tolist()
        selection_date = pd.to_datetime(month_nav['Date'].min())
        year_month_date = pd.to_datetime(f"{year_month}-01")

        prev_month_start = year_month_date - relativedelta(months=2)
        curr_month_start = year_month_date
        curr_month_end = year_month_date + pd.offsets.MonthEnd(0)

        stock_data = ticker_data[
            (ticker_data['Date'] >= prev_month_start)
            & (ticker_data['Date'] <= curr_month_end)
            & (ticker_data['Ticker'].isin(tickers))
        ].copy()
        
        stock_data = stock_data[stock_data['Date'] >= inception_date].copy()
        if stock_data.empty:
            continue
            
        stock_data['%change'] = stock_data.groupby('Ticker')['Close'].pct_change()

        stock_data_flt = stock_data[
            (stock_data['Date'] >= curr_month_start) & (stock_data['Date'] <= curr_month_end)
        ].copy()
        
        if stock_data_flt.empty:
            continue

        if not last_month_value:
            # First month allocation
            allocation_per_stock = initial_value / len(tickers)
            stock_allocations = {ticker: allocation_per_stock for ticker in tickers}
        else:
            # Carry over from last month
            stock_allocations = {ticker: last_month_value[ticker] for ticker in tickers if ticker in last_month_value}
            dropped_stocks = [ticker for ticker in last_month_value if ticker not in tickers]
            dropped_value = sum(last_month_value[ticker] for ticker in dropped_stocks)
            new_stocks = [ticker for ticker in tickers if ticker not in last_month_value]
            if new_stocks:
                allocation_per_stock = dropped_value / len(new_stocks) if dropped_value else 0.0
                for ticker in new_stocks:
                    stock_allocations[ticker] = allocation_per_stock

        for ticker, init_value in stock_allocations.items():
            ticker_index = stock_data_flt[stock_data_flt['Ticker'] == ticker].index
            if ticker_index.empty:
                continue
                
            ticker_df = stock_data_flt.loc[ticker_index].copy()
            
            stock_data_flt.loc[ticker_index, 'Initial_Allocation'] = init_value
            stock_data_flt.loc[ticker_index, 'Selection_Date'] = selection_date
            stock_data_flt.loc[ticker_index, 'Buy_Hold_Value'] = init_value * (
                (1 + stock_data_flt.loc[ticker_index, '%change'].fillna(0)).cumprod()
            )

            buy_price = float(ticker_df.iloc[0]['Close'])
            # Use carry-over quantity or calculate new
            quantity = last_month_quantity.get(ticker, init_value / buy_price if buy_price else 0.0)
            stock_data_flt.loc[ticker_index, 'Buy_Price'] = buy_price
            stock_data_flt.loc[ticker_index, 'Quantity'] = quantity
            
            if 'Real_Rank' in month_nav.columns:
                stock_data_flt.loc[ticker_index, 'Real_Rank'] = month_nav.loc[month_nav['Ticker'] == ticker, 'Real_Rank'].iloc[0]

        last_month_quantity = stock_data_flt.groupby('Ticker')['Quantity'].last().to_dict()
        last_month_value = stock_data_flt.groupby('Ticker')['Buy_Hold_Value'].last().to_dict()
        stock_data_flt['Total_Portfolio_Value'] = stock_data_flt.groupby('Date')['Buy_Hold_Value'].transform('sum')
        df_lis.append(stock_data_flt)

    final_df = pd.concat(df_lis, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)
    return final_df

def build_weighted_hedge_segment(hedge_prices, start_date, end_date, base_values, segment_name):
    segment = hedge_prices[
        (hedge_prices['Date'] >= start_date)
        & (hedge_prices['Date'] <= end_date)
        & (hedge_prices['Ticker'].isin(base_values))
    ][['Date', 'Ticker', 'Open', 'Close']].copy()
    
    if segment.empty:
        return segment

    segment = segment.sort_values(['Ticker', 'Date'])
    segment['%change'] = segment.groupby('Ticker')['Close'].pct_change()
    segment['Initial_Allocation'] = segment['Ticker'].map(base_values)
    segment['ret_factor'] = 1 + segment['%change'].fillna(0)
    segment['cum_factor'] = segment.groupby('Ticker')['ret_factor'].cumprod()
    segment['Buy_Hold_Value'] = segment['Initial_Allocation'] * segment['cum_factor']

    buy_prices = segment.groupby('Ticker')['Close'].transform('first')
    segment['Buy_Price'] = buy_prices
    segment['Quantity'] = np.where(buy_prices > 0, segment['Initial_Allocation'] / buy_prices, 0.0)
    segment['Selection_Date'] = start_date
    segment['Hedge_Segment'] = segment_name
    segment['Total_Portfolio_Value'] = segment.groupby('Date')['Buy_Hold_Value'].transform('sum')
    return segment.drop(columns=['ret_factor', 'cum_factor'])

def main():
    print(f"Starting portfolio process from {START_DATE}...")
    
    # 1. Load Momentum Selections
    nav_df_raw = pd.read_excel(INPUT_FILE).rename(columns={'End_Date': 'Date'})
    nav_df_raw['Date'] = pd.to_datetime(nav_df_raw['Date'])
    
    end_date_str = date.today().strftime('%Y-%m-%d')
    
    selected_cols = ['Date', 'Ticker']
    if 'Real_Rank' in nav_df_raw.columns:
        selected_cols.append('Real_Rank')
        
    start_dt = pd.to_datetime(START_DATE)
    start_month_first = start_dt.replace(day=1)
        
    nav_df = (
        nav_df_raw[(nav_df_raw['Date'] >= start_month_first) & (nav_df_raw['Date'] <= pd.to_datetime(end_date_str))]
        .reset_index(drop=True)[selected_cols]
    )
    nav_df['Year-Month'] = nav_df['Date'].dt.to_period('M').astype(str)
    
    # 2. Add GOLDBEES as the initial hedge leg
    goldbees_df = pd.DataFrame({
        'Date': nav_df['Date'].drop_duplicates().sort_values(),
        'Ticker': 'GOLDBEES'
    })
    if 'Real_Rank' in nav_df.columns:
        goldbees_df['Real_Rank'] = np.nan
    goldbees_df['Year-Month'] = pd.to_datetime(goldbees_df['Date']).dt.to_period('M').astype(str)
    
    # 3. Fetch Equity Data
    equity_tickers = nav_df['Ticker'].unique().tolist()
    print(f"Fetching data for {len(equity_tickers)} equity tickers...")
    equity_data, _ = fetch_truedata_history(equity_tickers, duration='3 Y')
    
    # 4. Fetch Initial Gold Data
    print("Fetching data for GOLDBEES...")
    gold_data, _ = fetch_truedata_history(['GOLDBEES'], duration='3 Y')
    
    # 5. Process Equity and Initial Gold Legs
    inception_dt = pd.to_datetime(START_DATE)
    print("Processing Equity leg...")
    final_df_equity = process_portfolio(nav_df, equity_data, EQUITY_ALLOCATION, inception_date=inception_dt)
    
    print("Processing Initial Gold leg...")
    final_df_gold_initial = process_portfolio(goldbees_df, gold_data, HEDGE_ALLOCATION, inception_date=inception_dt)
    
    # 6. Handle Hedge Rebalancing (Dec/Jan -> Feb -> Mar onward)
    # The requirement specifies that after 2025-11-30, the hedge book rebalances.
    portfolio_end_date = pd.to_datetime(final_df_equity['Date']).max()
    cutoff_date = pd.Timestamp('2025-11-30')
    
    # Equity leg stays as is.
    # Gold leg up to cutoff stays.
    old_gold_leg = final_df_gold_initial[final_df_gold_initial['Date'] <= cutoff_date].copy()
    
    # Calculate starting factor for hedge book rebalance
    if not old_gold_leg.empty:
        hedge_seed = float(old_gold_leg.sort_values('Date')['Buy_Hold_Value'].iloc[-1])
    else:
        # If START_DATE is after cutoff, use default allocation
        hedge_seed = HEDGE_ALLOCATION

    print(f"Hedge seed value for rebalancing: {hedge_seed}")
    
    # Fetch all hedge tickers
    hedge_tickers = ['GOLDBEES', 'SILVERBEES', 'MOGSEC', 'LIQUIDCASE']
    hedge_prices, _ = fetch_truedata_history(hedge_tickers, duration='3 Y')
    
    hedge_segments = []
    
    # Segment 1: Dec 2025 to Jan 2026 (60/20/20)
    decjan_start = pd.Timestamp('2025-12-01')
    decjan_end = min(pd.Timestamp('2026-01-31'), portfolio_end_date)
    
    if portfolio_end_date >= decjan_start:
        decjan_values = {'GOLDBEES': 0.60 * hedge_seed, 'SILVERBEES': 0.20 * hedge_seed, 'MOGSEC': 0.20 * hedge_seed}
        df_decjan = build_weighted_hedge_segment(hedge_prices, decjan_start, decjan_end, decjan_values, '2025-12_to_2026-01')
        if not df_decjan.empty:
            hedge_segments.append(df_decjan)
            
            # Segment 2: Feb 2026 (40/60)
            feb_start = pd.Timestamp('2026-02-01')
            feb_end = min(pd.Timestamp('2026-02-28'), portfolio_end_date)
            
            if portfolio_end_date >= feb_start:
                feb_factor = df_decjan.groupby('Date')['Buy_Hold_Value'].sum().iloc[-1]
                feb_values = {'GOLDBEES': 0.40 * feb_factor, 'MOGSEC': 0.60 * feb_factor}
                df_feb = build_weighted_hedge_segment(hedge_prices, feb_start, feb_end, feb_values, '2026-02')
                if not df_feb.empty:
                    hedge_segments.append(df_feb)
                    
                    # Segment 3: Mar 2026 onward (GOLDBEES / LIQUIDCASE)
                    mar_start = pd.Timestamp('2026-03-01')
                    if portfolio_end_date >= mar_start:
                        feb_last = df_feb[df_feb['Date'] == df_feb['Date'].max()].set_index('Ticker')['Buy_Hold_Value'].to_dict()
                        mar_values = {'GOLDBEES': feb_last.get('GOLDBEES', 0.0), 'LIQUIDCASE': feb_last.get('MOGSEC', 0.0)}
                        df_mar = build_weighted_hedge_segment(hedge_prices, mar_start, portfolio_end_date, mar_values, '2026-03_onward')
                        if not df_mar.empty:
                            hedge_segments.append(df_mar)

    # Combine all hedge parts
    if hedge_segments:
        rebalanced_hedge_leg = pd.concat(hedge_segments, ignore_index=True)
        final_hedge_df = pd.concat([old_gold_leg, rebalanced_hedge_leg], ignore_index=True)
    else:
        final_hedge_df = final_df_gold_initial

    # 7. Final Merge
    final_df = pd.concat([final_df_equity, final_hedge_df], ignore_index=True)
    final_df = final_df.sort_values(['Date', 'Ticker']).reset_index(drop=True)

    # 7b. Recompute Total_Portfolio_Value as combined equity + hedge for each date
    final_df['Total_Portfolio_Value'] = final_df.groupby('Date')['Buy_Hold_Value'].transform('sum')
    
    # 8. Export to CSV
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"Success! Portfolio exported to {OUTPUT_FILE}")
    
    # 9. Verify starting NAV
    start_nav = final_df[final_df['Date'] == final_df['Date'].min()]['Buy_Hold_Value'].sum()
    print(f"Starting Date: {final_df['Date'].min()}")
    print(f"Starting NAV: {start_nav}")

if __name__ == "__main__":
    main()
