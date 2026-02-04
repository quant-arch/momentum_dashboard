"""
Momentum Strategy Dashboard - Cloud Ready
==========================================
Single unified app with embedded data fetching, refresh capability, 
and dynamic date handling for Streamlit Cloud deployment.
"""

import os
import sys
import gc

# Ensure the script directory is in Python path for imports
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import tempfile
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
import logging
from fpdf import FPDF
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import concurrent.futures
from tqdm import tqdm

# Setup Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "cache")
UNIVERSE_FILE = os.path.join(BASE_DIR, "Ticker_Master.xlsx")


# ============================================================================
# EXCLUDED SYMBOLS CONFIGURATION
# ============================================================================
# Add stock symbols here that should NOT appear in the Live Tracking tab
# even if they exist in the Excel file. Useful for stocks that have exited
# the portfolio but are still in historical data.
# 
# To exclude a symbol: Add it to the list below (uppercase)
# Example: EXCLUDED_SYMBOLS = ['SILVERBEES', 'STOCKNAME', 'ANOTHERSYMBOL']
# ============================================================================
EXCLUDED_SYMBOLS = [
    'SILVERBEES',  # Exited portfolio - weightage redistributed to GOLDBEES/MOGSEC
    # Add more symbols here as needed in the future
]


# Ensure cache dir exists
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

# Configure Page
st.set_page_config(page_title="Investment Strategy Presentation", layout="wide")

# CSS for styling - Dark Blue Glassy Theme
st.markdown("""
<style>
    /* Main background */
    .stApp {
        background: linear-gradient(135deg, #0a1628 0%, #1a2744 50%, #0d1b2a 100%);
    }
    
    /* Glassmorphism effect for containers */
    .stMetric, .metric-card {
        background: rgba(26, 39, 68, 0.6);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 15px;
        margin: 5px;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1b2a 0%, #1a2744 100%);
        border-right: 1px solid rgba(255, 255, 255, 0.1);
    }
    
    /* Headers */
    h1, h2, h3, h4 {
        color: #e0e6ed !important;
    }
    
    /* Tables */
    .stDataFrame {
        background: rgba(26, 39, 68, 0.4);
        border-radius: 8px;
    }
    
    /* Buttons */
    .stButton > button {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: white;
    }
    
    .stButton > button:hover {
        background: linear-gradient(135deg, #2d5a87 0%, #3d7ab7 100%);
        border: 1px solid rgba(255, 255, 255, 0.4);
    }
    
    /* Force black borders on dataframe cells */
    [data-testid="stDataFrame"] table td,
    [data-testid="stDataFrame"] table th {
        border: 1px solid #000000 !important;
    }
    
    /* Also target styled dataframes */
    .dataframe td, .dataframe th {
        border: 1px solid #000000 !important;
    }

    /* Responsive Mobile Styles */
    @media only screen and (max-width: 768px) {
        /* Reduce padding for metrics */
        .stMetric, .metric-card {
            padding: 10px !important;
            margin: 2px !important;
        }
        
        /* Adjust header font sizes */
        h1 { font-size: 1.8rem !important; }
        h2 { font-size: 1.5rem !important; }
        h3 { font-size: 1.2rem !important; }
        
        /* Ensure charts take full width */
        .js-plotly-plot {
            width: 100% !important;
        }
        
        /* Table scrolling wrapper */
        .stDataFrame {
            overflow-x: auto !important;
            display: block !important;
        }
        
        /* Sidebar adjustments */
        section[data-testid="stSidebar"] {
            width: 100% !important; 
        }
        
        /* Adjust standard container padding */
        .block-container {
            padding-top: 2rem !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
        }
    }
</style>
""", unsafe_allow_html=True)

# Custom Plotly Template for dark blue theme
CHART_TEMPLATE = {
    'layout': {
        'paper_bgcolor': 'rgba(13, 27, 42, 0.8)',
        'plot_bgcolor': 'rgba(26, 39, 68, 0.6)',
        'font': {'color': '#e0e6ed'},
        'xaxis': {
            'gridcolor': 'rgba(255, 255, 255, 0.1)',
            'zerolinecolor': 'rgba(255, 255, 255, 0.2)'
        },
        'yaxis': {
            'gridcolor': 'rgba(255, 255, 255, 0.1)',
            'zerolinecolor': 'rgba(255, 255, 255, 0.2)'
        }
    }
}

# --- Config ---
START_DATE = '2021-01-01'
BENCHMARKS = {
    "Nifty 100": "NIFTY 100",
    "Nifty Midcap 150": "NIFTY MIDCAP 150",
    "Nifty Smallcap 250": "NIFTY SMLCAP 250",
    "Nifty 500": "NIFTY 500"
}

# --- Dynamic Date Calculation ---
def get_last_completed_month_end():
    """Returns the last day of the previous completed month."""
    today = datetime.now()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    return last_month_end.strftime('%Y-%m-%d')

def get_buffer_start():
    """Returns start date with buffer for calculations."""
    return '2020-01-01'

# --- TrueData Client ---
def get_truedata_credentials():
    """Get TrueData credentials from secrets or environment."""
    try:
        # Try Streamlit secrets first (for cloud)
        username = st.secrets["truedata"]["username"]
        password = st.secrets["truedata"]["password"]
    except:
        # Fallback to hardcoded (for local dev)
        username = "tdwsf695"
        password = "ocean@695"
    return username, password

# Import TrueDataClient
try:
    from td_client import TrueDataClient
except ImportError:
    st.error("td_client.py not found! Please ensure it is in the same directory.")
    st.stop()

# Global client instance
_td_client = None

def get_td_client():
    global _td_client
    if _td_client is None:
        username, password = get_truedata_credentials()
        _td_client = TrueDataClient(username, password)
    return _td_client

# --- Data Fetching Functions ---
def fetch_single_ticker(ticker, duration, bar_size):
    """Fetch data for a single ticker."""
    client = get_td_client()
    try:
        data = client.get_historic_data(ticker, duration=duration, bar_size=bar_size)
        return data
    except Exception as e:
        logging.error(f"Error fetching {ticker}: {e}")
        return None

def fetch_truedata_parallel(ticker_list, duration='1 Y', bar_size='EOD', max_workers=8):
    """Fetch data for multiple tickers in parallel."""
    results = []
    failed_tickers = []
    
    progress_bar = st.progress(0, text="Fetching data...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {
            executor.submit(fetch_single_ticker, ticker, duration, bar_size): ticker 
            for ticker in ticker_list
        }
        
        completed = 0
        total = len(ticker_list)
        
        for future in concurrent.futures.as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            try:
                data = future.result()
                if data is not None:
                    results.append(data)
                else:
                    failed_tickers.append(ticker)
            except Exception as exc:
                logging.error(f"{ticker} generated an exception: {exc}")
                failed_tickers.append(ticker)
            
            completed += 1
            progress_bar.progress(completed / total, text=f"Fetching data... {completed}/{total}")
            
            if len(results) % 100 == 0:
                gc.collect()
    
    progress_bar.empty()
                
    if results:
        final_df = pd.concat(results, ignore_index=True)
        if 'Date' in final_df.columns:
            final_df['Date'] = pd.to_datetime(final_df['Date'])
        gc.collect()
        return final_df, failed_tickers
    else:
        return pd.DataFrame(), failed_tickers

# --- Monthly Analysis Logic ---
def step_1_monthly_analysis(universe_file, start_date, end_date, top_n=20):
    """Run monthly momentum analysis."""
    # Read universe
    if universe_file.endswith(".csv"):
        df = pd.read_csv(universe_file)
    else:
        df = pd.read_excel(universe_file)
        
    stock_list = pd.DataFrame()
    if 'Symbol' in df.columns:
        stock_list['Ticker'] = df['Symbol']
    elif 'Ticker' in df.columns:
        stock_list['Ticker'] = df['Ticker']
    else:
        raise ValueError("Universe file must contain 'Symbol' or 'Ticker' column")
        
    if 'ISIN Code' in df.columns:
        stock_list['ISIN Code'] = df['ISIN Code']
    else:
        stock_list['ISIN Code'] = None
        
    stock_list['Ticker'] = stock_list['Ticker'].astype(str).str.replace(r'\.NS$', '', regex=True)
    stock_list['Ticker'] = stock_list['Ticker'].astype(str).str.replace(r'\.BO$', '', regex=True)
    stock_list = stock_list[~stock_list['Ticker'].str.upper().str.startswith('DUMMY')]
    
    symbol_list = stock_list["Ticker"].unique().tolist()
    
    # Fetch Data
    st.text("Fetching stock data...")
    data, errors = fetch_truedata_parallel(symbol_list, duration='10 Y', bar_size='EOD', max_workers=4)
    
    if data.empty:
        return None, None

    # Processing Logic
    data = data[['Date', 'Close', 'Ticker']]
    data.drop_duplicates(subset=['Date', 'Ticker'], inplace=True)
    prices = data.pivot(index="Date", columns="Ticker", values="Close").sort_index()
    
    total_start = pd.to_datetime(start_date)
    total_end = pd.to_datetime(end_date)
    
    # Rolling Windows
    windows = []
    current_start = total_start
    while True:
        current_end = current_start + relativedelta(months=6)
        if current_end > total_end:
            break
        
        window_prices = prices.loc[(prices.index >= current_start) & (prices.index < current_end)].copy()
        if not window_prices.empty:
            windows.append((current_start, current_end, window_prices))
        current_start += relativedelta(months=1)
        
    master_data = []
    
    for start, end, w_prices in windows:
        w_prices.dropna(axis=1, how='all', inplace=True)
        if w_prices.empty: continue
        
        try:
            month_groups = w_prices.groupby(w_prices.index.strftime('%Y-%m'))
            monthclose = month_groups.tail(1)
            monthstart = month_groups.head(1)
            monthstart.index = monthclose.index
            
            monchange = (monthclose - monthstart) / monthstart
            MOM = (monchange + 1).product() - 1
            mom = MOM * 100
            
            daily_ret = w_prices.pct_change(fill_method=None)
            positivechange = (daily_ret[daily_ret > 0].count() / daily_ret.count()) * 100
            negativechange = (daily_ret[daily_ret < 0].count() / daily_ret.count()) * 100
            
            result = pd.concat([positivechange, negativechange, mom], axis=1, join='inner')
            result.columns = ["Positive", "Negative", "Momentum"]
            result = result.reset_index().rename(columns={'index': 'Ticker'})
            
            result = pd.merge(result, stock_list[["Ticker", "ISIN Code"]], on="Ticker", how="left")
            
            df_res = result.copy()
            df_res["Rank_Mom"] = df_res["Momentum"].rank(method='min', ascending=False)
            df_res['FIP'] = df_res.apply(lambda row: row['Negative'] - row['Positive'] if row['Momentum'] > 0 else np.nan, axis=1)
            
            df_res.dropna(subset=['Momentum', 'FIP'], inplace=True)
            df_res["FIP_rank"] = df_res["FIP"].rank(method="first", ascending=True)
            df_res["Combined_Rank"] = df_res["Rank_Mom"] + df_res["FIP_rank"]
            
            # Sort by ranking first
            df_res = df_res.sort_values(by="Combined_Rank", ascending=True)
            
            # === PRICE FILTER: Exclude stocks with closing price >= Rs. 10,000 ===
            # Get the last closing price for each stock from the window
            last_prices = w_prices.iloc[-1]  # Last row of prices in this window
            df_res['Last_Close_Price'] = df_res['Ticker'].map(last_prices)
            
            # Filter: Keep only stocks with closing price < 10,000
            # If we don't have enough stocks under 10,000, take what we can get
            df_under_10k = df_res[df_res['Last_Close_Price'] < 10000].copy()
            
            # Select top_n stocks from the filtered list (already ranked)
            if len(df_under_10k) >= top_n:
                df_res = df_under_10k.head(top_n)
            else:
                # If not enough stocks under 10k, take all available under 10k
                # and fill remaining slots with next best ranked stocks (even if >= 10k)
                remaining_slots = top_n - len(df_under_10k)
                df_above_10k = df_res[df_res['Last_Close_Price'] >= 10000].head(remaining_slots)
                df_res = pd.concat([df_under_10k, df_above_10k], ignore_index=True)
            
            # Assign final ranks
            df_res = df_res.reset_index(drop=True)
            df_res["Real_Rank"] = range(1, len(df_res) + 1)
            df_res["Start_Date"] = start
            df_res["End_Date"] = end
            
            master_data.append(df_res)
        except Exception as e:
            logging.error(f"Window processing error: {e}")
            continue
            
    if not master_data:
        return None, None
        
    master_df = pd.concat(master_data, ignore_index=True)
    return master_df, data

# --- Portfolio Processing ---
def process_portfolio_logic(nav_df, ticker_data, initial_value=75, start_date_filter=None):
    """Process portfolio with daily granularity - matches original main_execution.py logic."""
    
    # ============================================================================
    # MANUAL REBALANCING CONFIGURATION
    # ============================================================================
    # When you need to rebalance GOLDBEES, SILVERBEES, or MOGSEC:
    # 1. Uncomment the dictionary below
    # 2. Set the target allocation values for the specific month
    # 3. Run the script
    # 4. Comment out this section again after running
    #
    # Example: If SILVERBEES exits and you want to redistribute its value:
    # manual_rebalancing = {
    #     '2026-02': {  # Year-Month when rebalancing occurs
    #         'GOLDBEES': 15.5,   # New allocation for GOLDBEES
    #         'MOGSEC': 9.5,      # New allocation for MOGSEC
    #         # 'SILVERBEES': 0   # If exiting, set to 0 or remove from portfolio
    #     }
    # }
    # ============================================================================
    
    # UNCOMMENT BELOW WHEN REBALANCING (then comment out after running)
    # manual_rebalancing = {
    #     # Add your rebalancing config here
    # }
    manual_rebalancing = {}  # Keep this line - default is no manual rebalancing
    
    df_lis = []
    last_month_value = {}
    last_month_quantity = {}
    
    # Ensure Year-Month column exists
    if 'Year-Month' not in nav_df.columns:
        nav_df['Year-Month'] = nav_df['Date'].dt.to_period('M').astype(str)
    
    year_months = nav_df['Year-Month'].unique()
    
    for year_month in year_months:
        tickers = nav_df[nav_df['Year-Month'] == year_month]['Ticker'].unique()
        year_month_date = pd.to_datetime(f"{year_month}-01")
        
        curr_month_start = year_month_date.strftime('%Y-%m-%d')
        curr_month_end = (year_month_date + pd.offsets.MonthEnd(0)).strftime('%Y-%m-%d')
        
        # Filter ticker data
        current_data = ticker_data[
            (ticker_data['Date'] >= curr_month_start) & 
            (ticker_data['Date'] <= curr_month_end) & 
            (ticker_data['Ticker'].isin(tickers))
        ].copy()
        
        if start_date_filter:
             current_data = current_data[current_data['Date'] >= start_date_filter]
             
        if current_data.empty:
            continue

        # Calculate daily % change
        current_data = current_data.sort_values(['Ticker', 'Date'])
        current_data['%change'] = current_data.groupby('Ticker')['Close'].pct_change(fill_method=None)
        
        # Allocation Logic
        if not last_month_value:
            # First month
            allocation_per_stock = initial_value / len(tickers)
            stock_allocations = {t: allocation_per_stock for t in tickers}
        else:
            # Rebalancing / Carry over
            stock_allocations = {}
            # Existing stocks
            for t in tickers:
                if t in last_month_value:
                    stock_allocations[t] = last_month_value[t]
            
            # Dropped stocks value
            dropped_stocks = [t for t in last_month_value if t not in tickers]
            dropped_value = sum(last_month_value[t] for t in dropped_stocks)
            
            # New stocks
            new_stocks = [t for t in tickers if t not in last_month_value]
            if new_stocks:
                new_allocation = dropped_value / len(new_stocks)
                for t in new_stocks:
                    stock_allocations[t] = new_allocation
        
        # === APPLY MANUAL REBALANCING (if configured for this month) ===
        if year_month in manual_rebalancing:
            print(f"⚠️ Applying manual rebalancing for {year_month}")
            rebal_config = manual_rebalancing[year_month]
            for ticker, allocation in rebal_config.items():
                if ticker in tickers:
                    print(f"   - {ticker}: Setting allocation to {allocation}")
                    stock_allocations[ticker] = allocation
        
        # Apply Value
        for tkr, init_val in stock_allocations.items():
            mask = current_data['Ticker'] == tkr
            if not mask.any(): continue
            
            # Compounding
            current_data.loc[mask, 'Buy_Hold_Value'] = init_val * (1 + current_data.loc[mask, '%change'].fillna(0)).cumprod()
            
            tkr_df = current_data[mask]
            buy_price = tkr_df.iloc[0]['Close']
            
            if tkr in last_month_quantity:
                qty = last_month_quantity[tkr]
            else:
                qty = init_val / buy_price if buy_price > 0 else 0
            
            current_data.loc[mask, 'Quantity'] = qty
            
        
        # Update Last Month
        last_values_series = current_data.groupby('Ticker')['Buy_Hold_Value'].last()
        last_month_value = last_values_series.to_dict()
        
        last_qty_series = current_data.groupby('Ticker')['Quantity'].last()
        last_month_quantity = last_qty_series.to_dict()
        
        # Total Portfolio
        total_daily = current_data.groupby('Date')['Buy_Hold_Value'].sum().reset_index()
        total_daily.rename(columns={'Buy_Hold_Value': 'Total_Portfolio_Value'}, inplace=True)
        
        current_data = pd.merge(current_data, total_daily, on='Date', how='left')
        
        df_lis.append(current_data)
        
    if df_lis:
        final_df = pd.concat(df_lis, ignore_index=True)
        return final_df
    return pd.DataFrame()

# --- Main Data Fetch Function ---
def fetch_and_cache_all_data(end_date):
    """Fetch all data and save to cache."""
    buffer_start = get_buffer_start()
    
    st.info(f"📊 Fetching data from {buffer_start} to {end_date}...")
    
    # 1. Run Monthly Analysis
    st.text("Step 1/5: Running monthly analysis...")
    master_df, stock_data = step_1_monthly_analysis(UNIVERSE_FILE, start_date=buffer_start, end_date=end_date)
    
    if master_df is None:
        st.error("Failed to run monthly analysis!")
        return False
    
    nav_df = master_df.rename(columns={'End_Date': 'Date'})
    nav_df['Date'] = pd.to_datetime(nav_df['Date'])
    nav_df['Year-Month'] = nav_df['Date'].dt.to_period('M').astype(str)
    nav_df.to_parquet(os.path.join(CACHE_DIR, "nav_df.parquet"), index=False)
    stock_data.to_parquet(os.path.join(CACHE_DIR, "stock_data.parquet"), index=False)
    
    # 2. Fetch Benchmark Data
    st.text("Step 2/5: Fetching benchmark data...")
    ticker_list = list(BENCHMARKS.values())
    bench_data, _ = fetch_truedata_parallel(ticker_list, duration='6 Y', bar_size='EOD', max_workers=8)
    bench_data.to_parquet(os.path.join(CACHE_DIR, "benchmark_data.parquet"), index=False)
    gc.collect()
    
    # 3. Process Portfolio
    st.text("Step 3/5: Processing portfolio...")
    # Re-read master_df for processing
    master_df['Date'] = pd.to_datetime(master_df['End_Date'])
    equity_res = process_portfolio_logic(master_df, stock_data, initial_value=75)
    equity_res['Date'] = pd.to_datetime(equity_res['Date'])
    equity_res.to_parquet(os.path.join(CACHE_DIR, "stock_level_df.parquet"), index=False)
    
    # 4. Compute daily NAV
    st.text("Step 4/5: Computing daily NAV...")
    strategy_curve = equity_res[['Date', 'Total_Portfolio_Value']].drop_duplicates(subset=['Date']).set_index('Date').sort_index()
    strategy_curve.columns = ['Equity_Value']
    strategy_curve['Returns'] = strategy_curve['Equity_Value'].pct_change(fill_method=None).fillna(0)
    strategy_curve['Strategy_Returns'] = strategy_curve['Returns'] * 0.75
    strategy_curve = strategy_curve[strategy_curve.index >= START_DATE]
    strategy_curve['My Strategy'] = 100 * (1 + strategy_curve['Strategy_Returns']).cumprod()
    
    bench_results = pd.DataFrame()
    for name, ticker in BENCHMARKS.items():
        mask = bench_data['Ticker'] == ticker
        if not mask.any():
            continue
        sub = bench_data[mask].set_index('Date').sort_index()
        sub.index = pd.to_datetime(sub.index)
        sub = sub[sub.index >= pd.to_datetime(START_DATE)]
        if sub.empty:
            continue
        series = sub['Close']
        series.name = name
        if bench_results.empty:
            bench_results = series.to_frame()
        else:
            bench_results = pd.merge(bench_results, series, left_index=True, right_index=True, how='outer')
    
    daily_nav = pd.merge(strategy_curve[['My Strategy']], bench_results, left_index=True, right_index=True, how='left')
    daily_nav = daily_nav[(daily_nav.index >= START_DATE) & (daily_nav.index <= end_date)]
    daily_returns = daily_nav.pct_change(fill_method=None).fillna(0)
    
    daily_nav.to_parquet(os.path.join(CACHE_DIR, "daily_nav.parquet"))
    daily_returns.to_parquet(os.path.join(CACHE_DIR, "daily_returns.parquet"))
    
    # 5. Compute Stock Stats
    st.text("Step 5/5: Computing stock statistics...")
    stock_stats = compute_stock_stats(nav_df, equity_res, end_date)
    stock_stats.to_parquet(os.path.join(CACHE_DIR, "stock_stats.parquet"), index=False)
    
    # Save metadata
    metadata = pd.DataFrame({'end_date': [end_date], 'updated_at': [datetime.now().isoformat()]})
    metadata.to_parquet(os.path.join(CACHE_DIR, "metadata.parquet"), index=False)
    
    st.success("✅ Data refresh complete!")
    return True

def compute_stock_stats(nav_df, stock_daily_df, end_date):
    """Compute stock-level statistics."""
    ndf = nav_df.copy()
    ndf['Date'] = pd.to_datetime(ndf['Date'])
    ndf = ndf[(ndf['Date'] >= START_DATE) & (ndf['Date'] <= end_date)]
    
    stats = []
    all_tickers = ndf['Ticker'].unique()
    
    for t in all_tickers:
        t_nav = ndf[ndf['Ticker'] == t].sort_values('Date')
        t_daily = stock_daily_df[stock_daily_df['Ticker'] == t].copy()
        
        avg_fip = t_nav['FIP'].mean() if 'FIP' in t_nav.columns else 0
        months_in = len(t_nav)
        
        if months_in > 0:
            t_nav = t_nav.copy()
            t_nav['month_diff'] = t_nav['Date'].dt.to_period('M').astype(int).diff()
            breaks = (t_nav['month_diff'] > 1).sum()
            re_entries_cnt = breaks
            last_stock_date = t_nav['Date'].max()
            port_end = ndf['Date'].max()
            left_cnt = breaks + (1 if last_stock_date < port_end else 0)
            
            # Calculate max consecutive months
            # Group by consecutive segments (break when month_diff > 1)
            t_nav['segment'] = (t_nav['month_diff'] > 1).cumsum()
            segment_lengths = t_nav.groupby('segment').size()
            max_consecutive = segment_lengths.max() if not segment_lengths.empty else months_in
        else:
            re_entries_cnt = 0
            left_cnt = 0
            max_consecutive = 0
        
        if not t_daily.empty:
            t_daily['Date'] = pd.to_datetime(t_daily['Date'])
            t_daily = t_daily.set_index('Date')
            
            m_close = t_daily['Close'].resample('M').last()
            if len(m_close) > 1:
                m_rets = m_close.pct_change(fill_method=None).dropna()
                avg_m_ret = m_rets.mean() * 100
            else:
                avg_m_ret = 0
                
            roll_max = t_daily['Close'].cummax()
            daily_dd = (t_daily['Close'] / roll_max) - 1
            m_dd = daily_dd.resample('M').min()
            avg_m_dd = m_dd.mean() * 100
        else:
            avg_m_ret = 0
            avg_m_dd = 0
        
        # Check if currently present in portfolio (last month matches portfolio end date)
        port_end = ndf['Date'].max()
        currently_present = "✅" if last_stock_date >= port_end else "❌"
            
        stats.append({
            "Stock Name": t,
            "Currently Present": currently_present,
            "Avg FIP Score": round(avg_fip, 2),
            "No. months in Portfolio": months_in,
            "Max Consecutive Months": int(max_consecutive),
            "Times Left": left_cnt,
            "Times Re-entered": re_entries_cnt,
            "Avg Monthly Return (%)": round(avg_m_ret, 2),
            "Avg Monthly Drawdown (%)": round(avg_m_dd, 2)
        })
        
    return pd.DataFrame(stats)

# --- Cache Checking ---
def check_cache_exists():
    """Check if all required cache files exist."""
    required_files = ["daily_nav.parquet", "daily_returns.parquet", "stock_level_df.parquet", 
                      "nav_df.parquet", "stock_stats.parquet", "metadata.parquet"]
    for f in required_files:
        if not os.path.exists(os.path.join(CACHE_DIR, f)):
            return False
    return True

def get_cache_metadata():
    """Get cache metadata."""
    try:
        meta = pd.read_parquet(os.path.join(CACHE_DIR, "metadata.parquet"))
        return meta['end_date'].iloc[0], meta['updated_at'].iloc[0]
    except:
        return None, None

def load_cached_data():
    """Load all data from Parquet cache files."""
    daily_nav = pd.read_parquet(os.path.join(CACHE_DIR, "daily_nav.parquet"))
    daily_returns = pd.read_parquet(os.path.join(CACHE_DIR, "daily_returns.parquet"))
    stock_level_df = pd.read_parquet(os.path.join(CACHE_DIR, "stock_level_df.parquet"))
    nav_df = pd.read_parquet(os.path.join(CACHE_DIR, "nav_df.parquet"))
    stock_stats = pd.read_parquet(os.path.join(CACHE_DIR, "stock_stats.parquet"))
    # Load raw OHLCV data for correlation analysis
    stock_data = pd.read_parquet(os.path.join(CACHE_DIR, "stock_data.parquet"))
    return daily_nav, daily_returns, stock_level_df, nav_df, stock_stats, stock_data

def get_current_portfolio_from_cache():
    """
    Read current portfolio stocks from cached parquet data.
    Returns: tuple (list of stock tickers, latest date, dataframe, source)
    """
    try:
        # Use cached data (generated in-memory during data refresh)
        if check_cache_exists():
            # Read from cached stock_level_df which contains all portfolio data
            stock_level_df = pd.read_parquet(os.path.join(CACHE_DIR, "stock_level_df.parquet"))
            nav_df = pd.read_parquet(os.path.join(CACHE_DIR, "nav_df.parquet"))
            
            # Use stock_level_df for current holdings
            daily_df = stock_level_df.copy()
            source = "cache"
        else:
            # No data available
            return None, None, None, None
        
        # Ensure Date column is datetime
        daily_df['Date'] = pd.to_datetime(daily_df['Date'])
        
        # Get the latest date
        latest_date = daily_df['Date'].max()
        
        # Get stocks from the latest date
        latest_stocks_df = daily_df[daily_df['Date'] == latest_date].copy()
        current_stocks = latest_stocks_df['Ticker'].unique().tolist()
        
        return current_stocks, latest_date, latest_stocks_df, source
    except Exception as e:
        logging.error(f"Error reading portfolio data: {e}")
        return None, None, None, None

# --- Helper Functions ---
@st.cache_data
def generate_trade_book(stock_df):
    trades = []
    stock_df = stock_df.copy()
    stock_df['YearMonth'] = stock_df['Date'].dt.to_period("M")
    
    for ticker, grp in stock_df.groupby('Ticker'):
        grp = grp.sort_values('Date')
        grp['prev_date'] = grp['Date'].shift(1)
        grp['days_gap'] = (grp['Date'] - grp['prev_date']).dt.days
        grp['group_id'] = (grp['days_gap'] > 10).cumsum()
        
        for pid, trade_grp in grp.groupby('group_id'):
            entry_row = trade_grp.iloc[0]
            exit_row = trade_grp.iloc[-1]
            
            buy_price = entry_row['Close']
            sell_price = exit_row['Close']
            
            if buy_price <= 0: continue
            
            qty = entry_row.get('Quantity', 1)
            duration = (exit_row['Date'] - entry_row['Date']).days
            
            pnl_abs = (sell_price - buy_price) * qty
            pnl_pct = ((sell_price / buy_price) - 1) * 100
            
            cagr = "N/A"
            if duration > 365:
                cagr_val = ((sell_price / buy_price) ** (365 / duration)) - 1
                cagr = f"{cagr_val * 100:.2f}%"
                
            trades.append({
                "Symbol": ticker,
                "Entry Date": entry_row['Date'].date(),
                "Buying Price": round(buy_price, 2),
                "Exit Date": exit_row['Date'].date(),
                "Selling Price": round(sell_price, 2),
                "Profit (Abs)": round(pnl_abs, 2),
                "Returns (%)": round(pnl_pct, 2),
                "CAGR": cagr
            })
            
    return pd.DataFrame(trades)

def get_monthly_heatmap(daily_series):
    monthly_ret = daily_series.resample('M').apply(lambda x: (1 + x).prod() - 1)
    df = monthly_ret.to_frame(name='Return')
    df['Year'] = df.index.year
    df['Month'] = df.index.month
    pivot = df.pivot(index='Year', columns='Month', values='Return')
    pivot.columns = [pd.to_datetime(f"2000-{m}-01").strftime('%b') for m in pivot.columns]
    pivot['Total Return'] = pivot.apply(lambda row: (1 + row.fillna(0)).prod() - 1, axis=1)
    return pivot * 100

# --- PDF Generation ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Investment Strategy Presentation', 0, 1, 'C')
        self.ln(5)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

def create_dynamic_pdf(report_items):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    
    # Title
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "Investment Strategy Report", ln=True, align='C')
    pdf.ln(10)
    
    for item in report_items:
        try:
            if item['type'] == 'header':
                if pdf.get_y() > 250: pdf.add_page()
                pdf.set_font("Arial", 'B', 14)
                pdf.cell(0, 10, item['text'], ln=True)
                pdf.ln(5)
                
            elif item['type'] == 'subheader':
                if pdf.get_y() > 260: pdf.add_page()
                pdf.set_font("Arial", 'B', 12)
                pdf.cell(0, 10, item['text'], ln=True)
                pdf.ln(2)
                
            elif item['type'] == 'text':
                pdf.set_font("Arial", size=10)
                pdf.multi_cell(0, 5, item['text'])
                pdf.ln(5)
                
            elif item['type'] == 'table':
                df = item['df']
                if df.empty: continue
                
                # Check space
                if pdf.get_y() > 240: pdf.add_page()
                
                pdf.set_font("Arial", 'B', 8)
                # Calculate widths
                page_width = 190
                # limit cols if too many
                cols = list(df.columns)[:15] 
                col_width = page_width / len(cols)
                line_height = 8
                
                # Header
                for col in cols:
                    pdf.cell(col_width, line_height, str(col)[:15], border=1) # truncate header
                pdf.ln(line_height)
                
                # Rows
                pdf.set_font("Arial", size=8)
                for _, row in df.iterrows():
                    if pdf.get_y() > 270: 
                        pdf.add_page()
                        # Re-print header
                        pdf.set_font("Arial", 'B', 8)
                        for col in cols:
                             pdf.cell(col_width, line_height, str(col)[:15], border=1)
                        pdf.ln(line_height)
                        pdf.set_font("Arial", size=8)
                        
                    for col in cols:
                        # simplistic string conversion
                        txt = str(row[col])
                        pdf.cell(col_width, line_height, txt[:20], border=1) # truncate content
                    pdf.ln(line_height)
                pdf.ln(5)
                
            elif item['type'] == 'image':
                if pdf.get_y() > 150: pdf.add_page()
                fig = item['fig']
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    # Write image with scale
                    fig.write_image(tmp.name, width=800, height=450, scale=2)
                    pdf.image(tmp.name, w=180)
                pdf.ln(5)
                
        except Exception as e:
            logging.error(f"Error rendering PDF item {item.get('type')}: {e}")
            continue
            
    return pdf.output(dest='S').encode('latin-1')

# --- Main App ---
def main():
    # Sidebar
    st.sidebar.title("⚙️ Controls")
    
    # Dynamic end date
    dynamic_end_date = get_last_completed_month_end()
    st.sidebar.info(f"📅 Data through: **{dynamic_end_date}**")
    
    # Cache status
    cache_exists = check_cache_exists()
    cached_end_date, cached_updated = get_cache_metadata()
    
    if cache_exists and cached_end_date:
        st.sidebar.success(f"✅ Cache available")
        col1, col2 = st.sidebar.columns(2)
        col1.metric("Data End Date", cached_end_date)
        col2.metric("Updated", cached_updated[:10] if cached_updated else "Unknown")
        
        # Helpful reminder
        with st.sidebar.expander("ℹ️ Moving to another system?"):
            st.info("📦 **Copy the entire `momentum_dashboard` folder** including the `cache/` subfolder to get identical results on another computer.")
    else:
        st.sidebar.warning("⚠️ No cache found\\nClick 'Refresh Data' below")
    
    # Refresh button
    if st.sidebar.button("🔄 Refresh Data", type="primary"):
        with st.spinner("Refreshing data... This may take a few minutes."):
            success = fetch_and_cache_all_data(dynamic_end_date)
            if success:
                st.cache_data.clear()
                st.rerun()
    
    st.sidebar.divider()
    
    
    # Check if we need to fetch data
    if not cache_exists:
        st.warning("⚠️ Data cache not found. Click 'Refresh Data' in the sidebar to fetch data.")
        return
        
    # Load data
    with st.spinner("Loading cached data..."):
        daily_nav, daily_returns, stock_level_df, raw_nav_df, stock_stats, stock_data = load_cached_data()
        gc.collect()
        
    if daily_nav is None or daily_nav.empty:
        st.error("Error loading data from cache.")
        return

    # Metrics Calculation
    end_date = daily_nav.index[-1]
    start_date_actual = daily_nav.index[0]
    days_diff = (end_date - start_date_actual).days
    
    cagr = ((daily_nav.iloc[-1] / daily_nav.iloc[0]) ** (365 / days_diff) - 1) * 100
    vol = daily_returns.std() * np.sqrt(252) * 100
    metrics_df = pd.DataFrame({'CAGR (%)': cagr, 'Daily Volatility (Ann. %)': vol}).reset_index().rename(columns={'index': 'Asset'})
    
    # PDF metrics
    pdf_metrics = metrics_df.copy()
    pdf_metrics['CAGR (%)'] = pdf_metrics['CAGR (%)'].map(lambda x: f"{x:.3f}%")
    pdf_metrics['Daily Volatility (Ann. %)'] = pdf_metrics['Daily Volatility (Ann. %)'].map(lambda x: f"{x:.3f}%")
    
    # Charts with custom dark blue theme
    rebased = daily_nav.apply(lambda x: x/x.iloc[0]*100)
    fig_line = px.line(rebased, title="NAV Growth (Base 100)")
    fig_line.update_layout(**CHART_TEMPLATE['layout'])
    
    metrics_df['Ratio'] = (metrics_df['CAGR (%)'] / metrics_df['Daily Volatility (Ann. %)']).abs().fillna(1)
    fig_scat = px.scatter(metrics_df, x='Daily Volatility (Ann. %)', y='CAGR (%)', 
                          color='Asset', size='Ratio', text='Asset', size_max=40,
                          title="Yearly Risk Return Trade Off")
    fig_scat.update_traces(textposition='top center')
    fig_scat.update_layout(**CHART_TEMPLATE['layout'])

    # Removed: Old PDF Export logic. Now handled inside Tab 1.

    # Verification Expander
    with st.expander("🔎 Calculation Verification"):
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Start:** {start_date_actual.date()}")
            st.write(f"**End:** {end_date.date()}")
        with col2:
            st.write(f"**Days:** {days_diff}")
            st.write(f"**Strategy End Value:** {daily_nav['My Strategy'].iloc[-1]:.2f}")

    # --- TABS ---
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "📁 Extract Data", "🔴 Live Tracking (15 min delay)"])
    
    # --- TAB 1: DASHBOARD ---
    with tab1:
        st.title("Strategy Dashboard")
        
        report_items = []
        
        # --- Section 1: Yearwise Analysis ---
        with st.expander("Yearwise Analysis", expanded=True):
            st.header("Yearwise Analysis")
            report_items.append({'type': 'header', 'text': 'Yearwise Analysis'})
            
            # 1.1 Metrics
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Metrics", value=True, key="chk_metrics"):
                st.subheader("Performance Metrics")
                disp_metrics = metrics_df.drop(columns=['Ratio'])
                disp_metrics['CAGR (%)'] = disp_metrics['CAGR (%)'].map(lambda x: f"{x:.3f}%")
                disp_metrics['Daily Volatility (Ann. %)'] = disp_metrics['Daily Volatility (Ann. %)'].map(lambda x: f"{x:.3f}%")
                st.table(disp_metrics)
                
                report_items.append({'type': 'subheader', 'text': 'Performance Metrics'})
                report_items.append({'type': 'table', 'df': disp_metrics})
            
            # 1.2 NAV Chart
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show NAV Chart", value=True, key="chk_nav"):
                st.plotly_chart(fig_line, use_container_width=True)
                report_items.append({'type': 'image', 'fig': fig_line})
                
            # 1.3 Risk Return
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Risk/Return", value=True, key="chk_risk"):
                st.plotly_chart(fig_scat, use_container_width=True)
                report_items.append({'type': 'image', 'fig': fig_scat})
                
            # 1.4 Monthly Drawdown
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Drawdown Chart", value=True, key="chk_dd"):
                st.subheader("Monthly Drawdown Analysis")
                # Calculate Monthly Drawdown (Re-calc here ensuring context)
                monthly_nav_dd = daily_nav.resample('M').last()
                rolling_max_m = monthly_nav_dd.cummax()
                drawdown_m = (monthly_nav_dd - rolling_max_m) / rolling_max_m * 100
                
                fig_dd_area = px.area(drawdown_m, title="Monthly Drawdowns (%)")
                fig_dd_area.update_layout(**CHART_TEMPLATE['layout'])
                fig_dd_area.update_xaxes(title="Date")
                fig_dd_area.update_yaxes(title="Drawdown (%)")
                st.plotly_chart(fig_dd_area, use_container_width=True)
                report_items.append({'type': 'image', 'fig': fig_dd_area})
                
            # 1.5 Monthly Returns Heatmap
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Returns Heatmap", value=True, key="chk_heatmap"):
                st.subheader("Strategy: Monthly Returns (%)")
                strat_monthly = get_monthly_heatmap(daily_returns['My Strategy'])
                
                def color_map(val):
                    bg = '#90EE90' if val > 0 else '#FFB6C1'
                    return f'background-color: {bg}; color: black; border: 2px solid #000000'
                    
                styled_monthly = strat_monthly.style.map(color_map, subset=pd.IndexSlice[:, strat_monthly.columns[:-1]]).format("{:.3f}%").set_table_styles([{'selector': 'td, th', 'props': [('border', '2px solid black'), ('font-size', '12px'), ('text-align', 'center'), ('min-width', '40px')]}])
                st.write(styled_monthly.to_html(), unsafe_allow_html=True)
                
                report_items.append({'type': 'subheader', 'text': 'Monthly Returns Table (%)'})
                report_items.append({'type': 'table', 'df': strat_monthly})
            
            # 1.6 Visualizers (Alpha/Beta/R2)
            st.divider()
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Alpha/Beta/R2", value=True, key="chk_abr"):
                # Alpha
                st.subheader("Alpha Visualizer")
                bench_opts = list(BENCHMARKS.keys())
                sel_bench = st.selectbox("Select Benchmark", bench_opts, key="bench_alpha")
                if sel_bench:
                    strat_m = get_monthly_heatmap(daily_returns['My Strategy'])
                    bench_m = get_monthly_heatmap(daily_returns[sel_bench])
                    alpha_mat = strat_m - bench_m
                    # Display Alpha
                    styled_alpha = alpha_mat.style.map(color_map, subset=pd.IndexSlice[:, alpha_mat.columns[:-1]]).format("{:.3f}%").set_table_styles([{'selector': 'td, th', 'props': [('border', '2px solid black'), ('font-size', '12px'), ('text-align', 'center'), ('min-width', '40px')]}])
                    st.write(styled_alpha.to_html(), unsafe_allow_html=True)
                    report_items.append({'type': 'subheader', 'text': f'Alpha Matrix (vs {sel_bench})'})
                    report_items.append({'type': 'table', 'df': alpha_mat})
                    
                # Beta
                st.subheader("Beta Visualizer")
                sel_bench_beta = st.selectbox("Select Benchmark for Beta", bench_opts, key="beta_bench_2")
                if sel_bench_beta:
                    strat_rets = daily_returns['My Strategy']
                    bench_rets = daily_returns[sel_bench_beta]
                    strat_rets_df = strat_rets.to_frame(name='Strategy')
                    strat_rets_df['Benchmark'] = bench_rets
                    strat_rets_df['Year'] = strat_rets_df.index.year
                    strat_rets_df['Month'] = strat_rets_df.index.month
                    beta_data = []
                    for (year, month), grp in strat_rets_df.groupby(['Year', 'Month']):
                        if len(grp) > 5:
                            cov = grp['Strategy'].cov(grp['Benchmark'])
                            var = grp['Benchmark'].var()
                            beta = cov / var if var != 0 else 0
                        else:
                            beta = np.nan
                        beta_data.append({'Year': year, 'Month': month, 'Beta': beta})
                    beta_df = pd.DataFrame(beta_data)
                    beta_pivot = beta_df.pivot(index='Year', columns='Month', values='Beta')
                    beta_pivot.columns = [pd.to_datetime(f"2000-{m}-01").strftime('%b') for m in beta_pivot.columns]
                    beta_pivot['Avg Beta'] = beta_pivot.mean(axis=1)
                    # Gradient color map for beta values
                    def beta_color_map(val):
                        if pd.isna(val):
                            return 'background-color: #cccccc; color: black; border: 2px solid #000000'
                        
                        # Gradient: Blue (negative) -> Green (0-0.7) -> Yellow (0.7-1.3) -> Red (>1.3)
                        if val < 0:
                            # Negative beta: Blue gradient
                            intensity = min(abs(val), 1)
                            r, g, b = 100, int(150 - intensity * 50), int(255 - intensity * 55)
                        elif val < 0.7:
                            # Low beta: Green
                            r, g, b = int(144 + (val / 0.7) * 50), 238, int(144 - val * 50)
                        elif val < 1.3:
                            # Medium beta around 1: Yellow/Orange
                            ratio = (val - 0.7) / 0.6
                            r, g, b = int(255), int(238 - ratio * 100), int(100 - ratio * 50)
                        else:
                            # High beta: Red gradient
                            excess = min(val - 1.3, 1)
                            r, g, b = int(255), int(138 - excess * 80), int(50 - excess * 30)
                        
                        return f'background-color: rgb({r},{g},{b}); color: black; border: 2px solid #000000'
                    
                    styled_beta = beta_pivot.style.map(beta_color_map).format("{:.3f}").set_table_styles([{'selector': 'td, th', 'props': [('border', '2px solid black')]}])
                    st.write(styled_beta.to_html(), unsafe_allow_html=True)
                    st.caption("🔵 Negative | 🟢 Low (0-0.7) | 🟡 Medium (0.7-1.3) | 🔴 High (>1.3)")
                    
                    report_items.append({'type': 'subheader', 'text': f'Beta Matrix (vs {sel_bench_beta})'})
                    report_items.append({'type': 'table', 'df': beta_pivot})

                # R2
                st.subheader("R² Visualizer")
                sel_bench_r2 = st.selectbox("Select Benchmark for R²", bench_opts, key="r2_bench_2")
                if sel_bench_r2:
                    strat_rets = daily_returns['My Strategy']
                    bench_rets = daily_returns[sel_bench_r2]
                    strat_rets_df = strat_rets.to_frame(name='Strategy')
                    strat_rets_df['Benchmark'] = bench_rets
                    strat_rets_df['Year'] = strat_rets_df.index.year
                    strat_rets_df['Month'] = strat_rets_df.index.month
                    r2_data = []
                    for (year, month), grp in strat_rets_df.groupby(['Year', 'Month']):
                        if len(grp) > 5:
                            corr = grp['Strategy'].corr(grp['Benchmark'])
                            r2 = corr ** 2 if not pd.isna(corr) else np.nan
                        else:
                            r2 = np.nan
                        r2_data.append({'Year': year, 'Month': month, 'R2': r2})
                    r2_df = pd.DataFrame(r2_data)
                    r2_pivot = r2_df.pivot(index='Year', columns='Month', values='R2')
                    r2_pivot.columns = [pd.to_datetime(f"2000-{m}-01").strftime('%b') for m in r2_pivot.columns]
                    r2_pivot['Avg R²'] = r2_pivot.mean(axis=1)
                    # Gradient color map for R² (0 to 1, higher is more correlated)
                    def r2_color_map(val):
                        if pd.isna(val):
                            return 'background-color: #cccccc; color: black; border: 2px solid #000000'
                        
                        # Gradient: Red (0) -> Yellow (0.5) -> Green (1)
                        if val < 0.3:
                            # Low R²: Red
                            r, g, b = 255, int(100 + val * 300), int(100 + val * 50)
                        elif val < 0.6:
                            # Medium R²: Yellow/Orange
                            ratio = (val - 0.3) / 0.3
                            r, g, b = 255, int(200 + ratio * 55), int(100 - ratio * 30)
                        else:
                            # High R²: Green
                            ratio = (val - 0.6) / 0.4
                            r, g, b = int(255 - ratio * 111), int(238), int(70 + ratio * 74)
                        
                        return f'background-color: rgb({r},{g},{b}); color: black; border: 2px solid #000000'
                    
                    styled_r2 = r2_pivot.style.map(r2_color_map).format("{:.3f}").set_table_styles([{'selector': 'td, th', 'props': [('border', '2px solid black')]}])
                    st.write(styled_r2.to_html(), unsafe_allow_html=True)
                    st.caption("🔴 Low R² (0-0.3): Independent | 🟡 Medium (0.3-0.6): Partial tracking | 🟢 High (0.6-1): Strong tracking")
                    
                    report_items.append({'type': 'subheader', 'text': f'R2 Matrix (vs {sel_bench_r2})'})
                    report_items.append({'type': 'table', 'df': r2_pivot})

        # --- Section 2: Monthwise Analysis ---
        with st.expander("Monthwise Analysis", expanded=True):
            st.header("Monthwise Analysis")
            report_items.append({'type': 'header', 'text': 'Monthwise Analysis'})
            
            c_y, c_m = st.columns(2)
            with c_y:
                sel_year = st.selectbox("Year", range(2021, 2027), key="analy_year_2")
            with c_m:
                months = ["January","February","March","April","May","June","July","August","September","October","November","December"]
                sel_month_name = st.selectbox("Month", months, key="analy_month_2")

            m_idx = months.index(sel_month_name) + 1
            mask_month = (daily_nav.index.year == sel_year) & (daily_nav.index.month == m_idx)
            m_nav = daily_nav[mask_month].copy()
            
            if not m_nav.empty:
                m_rets = m_nav.pct_change(fill_method=None).fillna(0)
                
                # 2.1 Cumulative Performance
                c1, c2 = st.columns([0.8, 0.2])
                if c2.checkbox("Show Cumulative Perf", value=True, key="chk_cum"):
                    st.subheader(f"Cumulative Performance: {sel_month_name} {sel_year}")
                    cum_ret_pct = ((1 + m_rets).cumprod() - 1) * 100
                    fig_cum = px.line(cum_ret_pct)
                    fig_cum.update_layout(**CHART_TEMPLATE['layout'])
                    st.plotly_chart(fig_cum, use_container_width=True)
                    report_items.append({'type': 'image', 'fig': fig_cum})
                
                # 2.2 Intra-Month Drawdown
                c1, c2 = st.columns([0.8, 0.2])
                if c2.checkbox("Show Intra-Month DD", value=True, key="chk_intra_dd"):
                    st.subheader("Intra-Month Drawdown (%)")
                    roll_max = m_nav.cummax()
                    dd = (m_nav - roll_max) / roll_max * 100
                    fig_dd = px.area(dd)
                    fig_dd.update_layout(**CHART_TEMPLATE['layout'])
                    st.plotly_chart(fig_dd, use_container_width=True)
                    report_items.append({'type': 'image', 'fig': fig_dd})
                
                # 2.3 Daily Returns Bar
                c1, c2 = st.columns([0.8, 0.2])
                if c2.checkbox("Show Daily Returns Grid", value=True, key="chk_daily_ret"):
                    st.subheader("Daily Returns")
                    cols_grid = st.columns(3)
                    for i, asset in enumerate(m_rets.columns):
                        with cols_grid[i % 3]:
                            colors = np.where(m_rets[asset] >= 0, 'green', 'red')
                            fig_bar = go.Figure()
                            fig_bar.add_trace(go.Bar(x=m_rets.index, y=m_rets[asset]*100, marker_color=colors, name=asset))
                            fig_bar.update_layout(title=asset, showlegend=False, height=300, **CHART_TEMPLATE['layout'])
                            st.plotly_chart(fig_bar, use_container_width=True)
                            # Adding all daily return charts might overflow PDF; add just Strategy for report
                            if asset == 'My Strategy':
                                report_items.append({'type': 'subheader', 'text': f'Daily Returns ({asset})'})
                                report_items.append({'type': 'image', 'fig': fig_bar})
            else:
                st.info("No data for this selection.")

        # --- Section 3: Stockwise Analysis ---
        with st.expander("Stockwise Analysis", expanded=True):
            st.header("Stockwise Analysis")
            report_items.append({'type': 'header', 'text': 'Stockwise Analysis'})
            
            # 3.1 Stock Stats
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Stock Stats", value=True, key="chk_stock_stats"):
                st.subheader("Stock Analysis Stats")
                st.dataframe(stock_stats)
                st.download_button("Download Stock Analysis (CSV)", stock_stats.to_csv(index=False).encode('utf-8'), "Stock_Analysis.csv", key="stock_download_2")
                report_items.append({'type': 'subheader', 'text': 'Stock Analysis Statistics'})
                report_items.append({'type': 'table', 'df': stock_stats})
                
            # 3.2 Top Stocks
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Top Stocks chart", value=True, key="chk_top_stocks"):
                st.subheader("Top Stocks: Yearly Presence in Portfolio")
                top_n_hist = st.selectbox("Select Top N Stocks", [5, 10, 15, 20], index=1, key="top_n_hist_2")
                top_stocks = stock_stats.nlargest(top_n_hist, 'No. months in Portfolio')['Stock Name'].tolist()
                
                yearly_presence = []
                for stock in top_stocks:
                    stock_presence_data = raw_nav_df[raw_nav_df['Ticker'] == stock].copy()
                    if stock_presence_data.empty: continue
                    stock_presence_data['Year'] = pd.to_datetime(stock_presence_data['Date']).dt.year
                    for year in stock_presence_data['Year'].unique():
                        year_data = stock_presence_data[stock_presence_data['Year'] == year]
                        months_count = len(year_data)
                        yearly_presence.append({'Stock': stock, 'Year': str(year), 'Months in Portfolio': months_count})
                        
                if yearly_presence:
                    presence_df = pd.DataFrame(yearly_presence)
                    presence_df = presence_df[presence_df['Year'] != '2020']
                    year_colors = ['#2ca02c', '#1f77b4', '#ff7f0e', '#d62728', '#9467bd', '#8c564b']
                    fig_presence = px.bar(presence_df, x='Stock', y='Months in Portfolio', color='Year', barmode='group',
                        title=f"Top {top_n_hist} Stocks: Months in Portfolio per Year", color_discrete_sequence=year_colors)
                    fig_presence.update_layout(**CHART_TEMPLATE['layout'])
                    st.plotly_chart(fig_presence, use_container_width=True)
                    report_items.append({'type': 'image', 'fig': fig_presence})
            
            # 3.3 Exits
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Exits Chart", value=True, key="chk_exits"):
                st.subheader("Stocks Exiting Portfolio (Monthly)")
                # (Recalculate exits_data just to be safely scoped or reuse earlier logic if extracted)
                # ... reusing logic inside directly ...
                exits_data = []
                # raw_nav_df Date/YearMonth must be set
                raw_nav_df['Date'] = pd.to_datetime(raw_nav_df['Date'])
                raw_nav_df['YearMonth'] = raw_nav_df['Date'].dt.to_period('M')
                all_periods = sorted(raw_nav_df['YearMonth'].unique())
                for i in range(len(all_periods) - 1):
                    current_period = all_periods[i]
                    next_period = all_periods[i + 1]
                    current_stocks_s = set(raw_nav_df[raw_nav_df['YearMonth'] == current_period]['Ticker'].unique())
                    next_stocks_s = set(raw_nav_df[raw_nav_df['YearMonth'] == next_period]['Ticker'].unique())
                    exited = current_stocks_s - next_stocks_s
                    if exited:
                        exits_data.append({'Year': str(current_period.year), 'Month': current_period.strftime('%b'), 'Month_Num': current_period.month, 'Stocks Exited': len(exited)})
                
                if exits_data:
                    exits_df = pd.DataFrame(exits_data)
                    exits_df = exits_df[exits_df['Year'] != '2020']
                    exits_df = exits_df.sort_values(['Year', 'Month_Num'])
                    fig_exits = px.bar(exits_df, x='Year', y='Stocks Exited', color='Month', barmode='group', title="Number of Stocks Exiting Portfolio")
                    fig_exits.update_layout(**CHART_TEMPLATE['layout'])
                    st.plotly_chart(fig_exits, use_container_width=True)
                    report_items.append({'type': 'image', 'fig': fig_exits})
            
            # 3.4 Risk Analysis (Corr/Cov)
            c1, c2 = st.columns([0.8, 0.2])
            if c2.checkbox("Show Risk Heatmaps", value=True, key="chk_cov_corr"):
                st.subheader("Portfolio Risk Analysis: Correlation & Covariance")
                current_stocks = stock_stats[stock_stats['Currently Present'] == '✅']['Stock Name'].tolist()
                
                if current_stocks and len(current_stocks) > 1:
                    stock_data['Date'] = pd.to_datetime(stock_data['Date'])
                    stock_data_filtered = stock_data[stock_data['Ticker'].isin(current_stocks)].copy()
                    
                    if not stock_data_filtered.empty and 'Close' in stock_data_filtered.columns:
                        stock_data_filtered['YearMonth'] = stock_data_filtered['Date'].dt.to_period('M')
                        first_months = stock_data_filtered.groupby('Ticker')['YearMonth'].min()
                        common_start_month = first_months.max()
                        stock_data_common = stock_data_filtered[stock_data_filtered['YearMonth'] >= common_start_month]
                        monthly_close = stock_data_common.groupby(['Ticker', 'YearMonth'])['Close'].last().reset_index()
                        monthly_pivot = monthly_close.pivot(index='YearMonth', columns='Ticker', values='Close').dropna()
                        monthly_returns = monthly_pivot.pct_change(fill_method=None).dropna()
                        
                        if not monthly_returns.empty:
                            col_a, col_b = st.columns(2)
                            with col_a:
                                corr_matrix = monthly_returns.corr()
                                corr_text = np.round(corr_matrix.values, 2)
                                fig_corr = go.Figure(data=go.Heatmap(z=corr_matrix.values, x=corr_matrix.columns, y=corr_matrix.index, colorscale='RdBu_r', zmid=0, zmin=-1, zmax=1, text=corr_text, texttemplate="%{text}"))
                                fig_corr.update_layout(title="Returns Correlation", **CHART_TEMPLATE['layout'])
                                st.plotly_chart(fig_corr, use_container_width=True)
                                report_items.append({'type': 'image', 'fig': fig_corr})
                            with col_b:
                                cov_matrix = monthly_returns.cov() * 100
                                cov_text = np.round(cov_matrix.values, 2)
                                fig_cov = go.Figure(data=go.Heatmap(z=cov_matrix.values, x=cov_matrix.columns, y=cov_matrix.index, colorscale='Viridis', text=cov_text, texttemplate="%{text}"))
                                fig_cov.update_layout(title="Variance-Covariance (x100)", **CHART_TEMPLATE['layout'])
                                st.plotly_chart(fig_cov, use_container_width=True)
                                report_items.append({'type': 'image', 'fig': fig_cov})
    
    # Export Button (Sidebar)
    # We update the export button logic to use 'report_items'
    if st.sidebar.button("📄 Export PDF Report"):
        with st.spinner("Generating Dynamic Report..."):
            try:
                if not report_items:
                    st.sidebar.warning("Report is empty. Please enable some sections.")
                else:
                    pdf_bytes = create_dynamic_pdf(report_items)
                    st.sidebar.download_button("📥 Download PDF", pdf_bytes, "Strategy_Report.pdf", "application/pdf")
            except Exception as e:
                st.sidebar.error(f"PDF Error: {e}")
                logging.error(f"PDF Gen Error: {e}")

    # --- TAB 2: EXTRACT DATA ---
    with tab2:
        st.title("Data Extraction Hub")
        
        c1, c2 = st.columns(2)
        start_d = c1.date_input("Start Date", pd.to_datetime(START_DATE))
        end_d = c2.date_input("End Date", daily_nav.index[-1].date())
        
        selected_assets = st.multiselect("Select Assets", options=daily_nav.columns, default=list(daily_nav.columns))
        
        st.subheader("1. Daily NAV & Returns")
        mask = (daily_nav.index >= pd.Timestamp(start_d)) & (daily_nav.index <= pd.Timestamp(end_d))
        export_nav = daily_nav.loc[mask, selected_assets].copy()
        for c in export_nav.columns:
            export_nav[f"{c} Ret%"] = export_nav[c].pct_change(fill_method=None) * 100
        
        st.dataframe(export_nav.head())
        st.download_button("Download NAV Data (CSV)", export_nav.to_csv().encode('utf-8'), "NAV_Data.csv", key="nav_download")
        
        st.divider()
        
        st.subheader("2. Strategy Trade Book")
        if stock_level_df is not None and not stock_level_df.empty:
            trade_book = generate_trade_book(stock_level_df)
            
            if not trade_book.empty:
                t_mask = (pd.to_datetime(trade_book['Entry Date']) >= pd.Timestamp(start_d)) & \
                         (pd.to_datetime(trade_book['Entry Date']) <= pd.Timestamp(end_d))
                final_trades = trade_book[t_mask].copy()
                
                st.dataframe(final_trades)
                st.download_button("Download Trade Book (CSV)", final_trades.to_csv(index=False).encode('utf-8'), "Trade_Book.csv", key="tradebook_download")
            else:
                st.info("No trades found.")

    # --- TAB 3: LIVE TRACKING ---
    with tab3:
        st.title("🔴 Live Portfolio Tracking")
        st.caption("Data updated with up to 15 minutes delay")
        
        
        
        # Load portfolio directly from Excel file (Source of Truth for manual moves)
        # Allows capturing manual January changes recorded in the file
        excel_path = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials\Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx"
        portfolio_entries = {}
        df = None  # Initialize df variable
        latest_date = None  # Initialize latest_date variable
        
        if os.path.exists(excel_path):
            try:
                # Read Excel
                df = pd.read_excel(excel_path)
                df['Date'] = pd.to_datetime(df['Date'])
                
                # FILTER: Strictly enforce Nov 10, 2025 as inception
                df = df[df['Date'] >= '2025-11-10']
                
                if df.empty:
                     st.warning("⚠️ No data found from Nov 10, 2025 onwards in Excel file.")
                
                # Get latest date
                latest_date = df['Date'].max()
                
                # Get stocks active on latest date
                current_holdings = df[df['Date'] == latest_date]
                
                # === FILTER OUT EXCLUDED SYMBOLS (Live Tracking only) ===
                # Remove symbols like SILVERBEES that have exited the portfolio
                if EXCLUDED_SYMBOLS:
                    current_holdings = current_holdings[~current_holdings['Ticker'].isin(EXCLUDED_SYMBOLS)]
                    excluded_count = len([s for s in EXCLUDED_SYMBOLS if s in df[df['Date'] == latest_date]['Ticker'].values])
                    if excluded_count > 0:
                        st.info(f"ℹ️ Excluded {excluded_count} symbol(s) from Live Tracking: {', '.join(EXCLUDED_SYMBOLS)}")
                
                # For each active stock, find its LATEST entry date/price (most recent re-entry)
                for ticker in current_holdings['Ticker'].unique():
                    # Get this stock's full history (sorted by date)
                    stock_hist = df[df['Ticker'] == ticker].sort_values('Date').reset_index(drop=True)
                    
                    # === FIND LATEST RE-ENTRY DATE (IMPROVED) ===
                    # Check month-by-month from inception to find continuous holding period
                    # This handles cases where stock is absent for entire months
                    
                    if len(stock_hist) == 0:
                        continue
                    
                    # Get all unique year-months this stock appears in
                    stock_hist['YearMonth'] = stock_hist['Date'].dt.to_period('M')
                    present_months = set(stock_hist['YearMonth'])
                    
                    # Generate all months from inception (Nov 2025) to latest date
                    inception_month = pd.Period('2025-11', freq='M')
                    latest_month = stock_hist['YearMonth'].max()
                    
                    all_months = []
                    current_month = latest_month
                    while current_month >= inception_month:
                        all_months.insert(0, current_month)
                        current_month -= 1
                    
                    # Work backwards from latest month to find start of continuous period
                    continuous_start_month = latest_month
                    
                    for i in range(len(all_months) - 1, 0, -1):
                        month = all_months[i]
                        prev_month = all_months[i-1]
                        
                        # If previous month is missing, we found a gap
                        if prev_month not in present_months:
                            continuous_start_month = month
                            break
                    else:
                        # No gap found - continuous since inception
                        continuous_start_month = inception_month
                    
                    # Get the earliest date in the continuous start month
                    continuous_data = stock_hist[stock_hist['YearMonth'] >= continuous_start_month]
                    entry_date = continuous_data['Date'].min()
                    entry_row = continuous_data.iloc[0]
                    
                    # Use Open price from entry date, fallback to Close if Open not available
                    entry_price = entry_row['Open'] if 'Open' in df.columns and pd.notna(entry_row.get('Open')) else entry_row['Close']
                    
                    portfolio_entries[ticker] = {
                        'entry_date': entry_date,
                        'entry_price': entry_price
                    }
                
                st.success(f"✅ **Portfolio synced with Excel** | As of: **{latest_date.strftime('%Y-%m-%d')}** | **{len(portfolio_entries)} stocks**")
                st.caption(f"📁 Source: {os.path.basename(excel_path)}")
                
            except Exception as e:
                st.error(f"Error reading Excel: {e}")
                logging.error(f"Excel read error: {e}")
        
        # If Excel doesn't exist or failed, try current_portfolio.csv (for Streamlit Cloud)
        if not portfolio_entries:
            csv_path = os.path.join(BASE_DIR, "current_portfolio.csv")
            if os.path.exists(csv_path):
                try:
                    st.info("📄 Loading current portfolio from current_portfolio.csv...")
                    portfolio_csv = pd.read_csv(csv_path)
                    
                    # Get latest date from stock_level_df for reference
                    latest_date = stock_level_df['Date'].max()
                    
                    # Track missing stocks
                    missing_stocks = []
                    
                    for _, row in portfolio_csv.iterrows():
                        ticker = row['Ticker']
                        
                        # Skip excluded symbols
                        if ticker in EXCLUDED_SYMBOLS:
                            continue
                        
                        # Get entry date from CSV or use default
                        if pd.notna(row.get('Entry_Date')):
                            entry_date = pd.to_datetime(row['Entry_Date'])
                        else:
                            # Default to start of cached data for this ticker or Nov 10, 2025
                            ticker_data = stock_level_df[stock_level_df['Ticker'] == ticker]
                            if not ticker_data.empty:
                                entry_date = ticker_data['Date'].min()
                            else:
                                # Use default inception date if not in cache
                                entry_date = pd.to_datetime('2025-11-10')
                                missing_stocks.append(ticker)
                        
                        # Get entry price from CSV or look up from cache
                        if pd.notna(row.get('Entry_Price')) and row['Entry_Price'] > 0:
                            entry_price = float(row['Entry_Price'])
                        else:
                            # Try to look up from cache data at entry date
                            ticker_at_entry = stock_level_df[
                                (stock_level_df['Ticker'] == ticker) & 
                                (stock_level_df['Date'] >= entry_date)
                            ].sort_values('Date')
                            
                            if not ticker_at_entry.empty:
                                entry_price = ticker_at_entry.iloc[0]['Close']
                            else:
                                # Stock not in cache - fetch from API
                                try:
                                    client = get_td_client()
                                    data = client.get_historic_data(ticker, duration='3 M', bar_size='EOD')
                                    if data is not None and not data.empty:
                                        data['Date'] = pd.to_datetime(data['Date'])
                                        # Get price on or after entry date
                                        entry_data = data[data['Date'] >= entry_date]
                                        if not entry_data.empty:
                                            entry_price = entry_data.iloc[0]['Close']
                                        else:
                                            # Use first available price
                                            entry_price = data.iloc[0]['Close']
                                    else:
                                        st.warning(f"⚠️ Could not fetch data for {ticker}, skipping...")
                                        continue
                                except Exception as e:
                                    st.warning(f"⚠️ Error fetching {ticker}: {e}, skipping...")
                                    continue
                        
                        portfolio_entries[ticker] = {
                            'entry_date': entry_date,
                            'entry_price': entry_price
                        }
                    
                    # Set df to stock_level_df for compatibility
                    df = stock_level_df
                    
                    # Show info about missing stocks
                    if missing_stocks:
                        st.info(f"ℹ️ Fetched data for {len(missing_stocks)} stocks not in momentum history: {', '.join(missing_stocks[:5])}{'...' if len(missing_stocks) > 5 else ''}")
                    
                    st.success(f"✅ **Portfolio loaded from CSV** | **{len(portfolio_entries)} stocks**")
                    st.caption("📁 Source: current_portfolio.csv")
                    
                except Exception as e:
                    st.error(f"Error reading current_portfolio.csv: {e}")
                    logging.error(f"CSV read error: {e}")
        
        # Final fallback to cache if still no portfolio entries
        if not portfolio_entries:
            st.warning("⚠️ No portfolio configuration found. Using cached portfolio data.")
            
            # Fallback to cached data - get current portfolio from stock_level_df
            try:
                # Get the latest date from cached data
                latest_date = stock_level_df['Date'].max()
                
                # Get stocks active on latest date
                current_holdings = stock_level_df[stock_level_df['Date'] == latest_date]
                
                # Filter out excluded symbols
                if EXCLUDED_SYMBOLS:
                    current_holdings = current_holdings[~current_holdings['Ticker'].isin(EXCLUDED_SYMBOLS)]
                
                # For each active stock, find entry date/price from cache
                for ticker in current_holdings['Ticker'].unique():
                    stock_hist = stock_level_df[stock_level_df['Ticker'] == ticker].sort_values('Date')
                    
                    # Get first occurrence as entry
                    entry_row = stock_hist.iloc[0]
                    entry_date = entry_row['Date']
                    entry_price = entry_row['Close']
                    
                    portfolio_entries[ticker] = {
                        'entry_date': entry_date,
                        'entry_price': entry_price
                    }
                
                # Also set df to stock_level_df for compatibility with downstream code
                df = stock_level_df
                
                st.success(f"✅ **Portfolio loaded from cache** | As of: **{pd.to_datetime(latest_date).strftime('%Y-%m-%d')}** | **{len(portfolio_entries)} stocks**")
                st.caption("📁 Source: Cached data")
                
            except Exception as e:
                st.error(f"Error loading from cache: {e}")
                logging.error(f"Cache fallback error: {e}")
                portfolio_entries = {}

        current_portfolio_stocks = list(portfolio_entries.keys())
        
        # Refresh button
        refresh_live = st.button("🔄 Refresh Live Prices (15 min delay)", type="primary", key="refresh_live_btn")
        
        if not current_portfolio_stocks:
            st.warning("No stocks currently in portfolio.")
        else:
            # Session state for live data
            if 'live_data' not in st.session_state or refresh_live:
                with st.spinner("Fetching latest prices (up to 15 min delay)..."):
                    # Fetch latest prices for current portfolio stocks
                    live_prices = {}
                    client = get_td_client()
                    
                    # Progress indicator
                    progress_text = st.empty()
                    progress_bar = st.progress(0)
                    
                    for i, ticker in enumerate(current_portfolio_stocks):
                        try:
                            # Fetch last 1 day data at 15-minute interval
                            data = client.get_historic_data(ticker, duration='1 D', bar_size='15 mins')
                            if data is not None and not data.empty:
                                # Get the latest closing price
                                last_close = data['Close'].iloc[-1]
                                last_time = data['Date'].iloc[-1] if 'Date' in data.columns else datetime.now()
                                live_prices[ticker] = {'price': last_close, 'time': last_time}
                        except Exception as e:
                            logging.error(f"Error fetching live price for {ticker}: {e}")
                        
                        progress_bar.progress((i + 1) / len(current_portfolio_stocks))
                        progress_text.text(f"Fetching {ticker}... ({i+1}/{len(current_portfolio_stocks)})")
                    
                    progress_bar.empty()
                    progress_text.empty()
                    
                    st.session_state.live_data = live_prices
                    st.session_state.live_fetch_time = datetime.now()
            
            # Show last update time
            if 'live_fetch_time' in st.session_state:
                st.info(f"📅 Last updated: {st.session_state.live_fetch_time.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # --- CALCULATE PORTFOLIO METRICS (NAV - Normalized to Base 100) ---
            # Calculate actual initial NAV (Nov 10, 2025)
            actual_initial_nav = 0
            if 'df' in locals() and not df.empty:
                # Find the start date (Nov 10 or closest after)
                start_date_mask = df['Date'] >= '2025-11-10'
                if start_date_mask.any():
                    start_date = df[start_date_mask]['Date'].min()
                    initial_nav_df = df[df['Date'] == start_date]
                    actual_initial_nav = initial_nav_df['Buy_Hold_Value'].sum() if 'Buy_Hold_Value' in df.columns else 0
            
            # === NORMALIZE TO BASE 100 ===
            # Set initial NAV as 100 for easy percentage interpretation
            initial_nav = 100.0
            
            # Current Live NAV (actual portfolio value)
            actual_live_nav = 0
            live_tracking_data = []
            today = datetime.now()
            
            for ticker, entry_info in portfolio_entries.items():
                entry_date = entry_info['entry_date']
                entry_price = entry_info['entry_price']
                
                # Get current price
                current_price = None
                if ticker in st.session_state.get('live_data', {}):
                    current_price = st.session_state.live_data[ticker]['price']
                else:
                     # Fallback to Excel/Cache price
                    if 'df' in locals():
                        # Get latest price from Excel for this ticker
                        latest_ticker_row = df[(df['Ticker'] == ticker) & (df['Date'] == latest_date)]
                        if not latest_ticker_row.empty:
                            current_price = latest_ticker_row.iloc[0]['Close']
                
                # Calculate Stock Weight/Value Contribution
                # Value = (Shares * Price). Approximate Shares = Last_Recorded_Value / Last_Recorded_Price
                current_value = 0
                if 'df' in locals() and not df.empty and current_price is not None:
                     latest_ticker_row = df[(df['Ticker'] == ticker) & (df['Date'] == latest_date)]
                     if not latest_ticker_row.empty:
                         last_val = latest_ticker_row.iloc[0]['Buy_Hold_Value']
                         last_price = latest_ticker_row.iloc[0]['Close']
                         if last_price > 0:
                             shares = last_val / last_price
                             current_value = shares * current_price
                             actual_live_nav += current_value
            
            # Normalize current NAV to base 100
            if actual_initial_nav > 0:
                live_nav = 100.0 * (actual_live_nav / actual_initial_nav)
            else:
                live_nav = 100.0
            
            # Display Portfolio Level Returns
            if actual_initial_nav > 0 and actual_live_nav > 0:
                total_return_pct = ((actual_live_nav - actual_initial_nav) / actual_initial_nav) * 100
                
                st.markdown("---")
                col_p1, col_p2, col_p3 = st.columns(3)
                with col_p1:
                    st.metric("🏁 Initial NAV (Nov 10)", f"{initial_nav:.2f}", help="Normalized base value = 100")
                with col_p2:
                    st.metric("💰 Current NAV (Live)", f"{live_nav:.2f}", help=f"Actual value: Rs.{actual_live_nav:,.2f}")
                with col_p3:
                    st.metric("🚀 Return Since Inception", f"{total_return_pct:.2f}%", delta=f"{total_return_pct:.2f}%")
                st.markdown("---")

            # Calculate individual stock returns
            for ticker, entry_info in portfolio_entries.items():
                entry_date = entry_info['entry_date']
                entry_price = entry_info['entry_price']
                
                # Fetch entry price if not provided
                if entry_price is None or pd.isna(entry_price):
                    ticker_data = stock_level_df[stock_level_df['Ticker'] == ticker].copy()
                    if not ticker_data.empty:
                        ticker_data['Date'] = pd.to_datetime(ticker_data['Date'])
                        ticker_data = ticker_data.sort_values('Date')
                        # Get price on  or after entry date
                        entry_data = ticker_data[ticker_data['Date'] >= entry_date]
                        if not entry_data.empty:
                            entry_price = entry_data.iloc[0]['Open']  # Use Open from entry date
                        else:
                            continue  # Skip if can't find entry price
                    else:
                        continue
                
                # Get current price from live data or cached data
                current_price = None
                if ticker in st.session_state.get('live_data', {}):
                    current_price = st.session_state.live_data[ticker]['price']
                else:
                    # Fallback to Excel data first, then stock_level_df
                    if 'df' in locals() and not df.empty:
                        latest_ticker_row = df[(df['Ticker'] == ticker) & (df['Date'] == latest_date)]
                        if not latest_ticker_row.empty:
                            current_price = latest_ticker_row.iloc[0]['Close']
                    
                    # If still None, fallback to cached data
                    if current_price is None:
                        ticker_data_fallback = stock_level_df[stock_level_df['Ticker'] == ticker].copy()
                        if not ticker_data_fallback.empty:
                            ticker_data_fallback['Date'] = pd.to_datetime(ticker_data_fallback['Date'])
                            ticker_data_fallback = ticker_data_fallback.sort_values('Date')
                            current_price = ticker_data_fallback['Close'].iloc[-1]
                
                # Calculate holding period
                holding_days = (today - entry_date).days
                holding_years = holding_days / 365.0
                
                # Calculate returns
                if entry_price > 0 and current_price is not None:
                    if holding_years < 1:
                        # Absolute return for < 1 year
                        returns = ((current_price / entry_price) - 1) * 100
                        return_type = "Abs %"
                    else:
                        # CAGR for >= 1 year
                        returns = ((current_price / entry_price) ** (1 / holding_years) - 1) * 100
                        return_type = "CAGR %"
                else:
                    returns = 0
                    return_type = "N/A"
                
                live_tracking_data.append({
                    "Entry Date": entry_date.strftime('%Y-%m-%d'),
                    "Symbol": ticker,
                    "Buy Price (₹)": round(entry_price, 2),
                    "Current Price (₹)": round(current_price, 2) if current_price else "N/A",
                    "Returns": round(returns, 3) if returns != 0 else 0,
                    "Return Type": return_type,
                    "Holding Days": holding_days
                })
            
            if live_tracking_data:
                live_df = pd.DataFrame(live_tracking_data)
                
                # Summary metrics
                st.subheader("📊 Portfolio Summary")
                metric_cols = st.columns(4)
                
                total_stocks = len(live_df)
                profitable = len(live_df[live_df['Returns'] > 0])
                avg_return = live_df['Returns'].mean()
                
                with metric_cols[0]:
                    st.metric("Total Stocks", total_stocks)
                with metric_cols[1]:
                    st.metric("Profitable", profitable, delta=f"{(profitable/total_stocks)*100:.1f}%" if total_stocks > 0 else "0%")
                with metric_cols[2]:
                    st.metric("Loss Making", total_stocks - profitable)
                with metric_cols[3]:
                    st.metric("Avg Return", f"{avg_return:.3f}%", delta="Positive" if avg_return > 0 else "Negative")
                
                st.divider()
                
                # Display the live tracking table
                st.subheader("📋 Current Portfolio Holdings")
                
                # Style the dataframe
                def color_returns(val):
                    if isinstance(val, (int, float)):
                        if val > 0:
                            return 'background-color: #90EE90; color: black'
                        elif val < 0:
                            return 'background-color: #FFB6C1; color: black'
                    return ''
                
                styled_live = live_df.style.applymap(color_returns, subset=['Returns'])
                st.dataframe(styled_live, use_container_width=True, hide_index=True)
                
                # Download button
                st.download_button(
                    "📥 Download Live Portfolio (CSV)",
                    live_df.to_csv(index=False).encode('utf-8'),
                    f"Live_Portfolio_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    key="live_portfolio_download"
                )
            else:
                st.warning("Could not retrieve entry data for current portfolio stocks.")


if __name__ == "__main__":
    main()
