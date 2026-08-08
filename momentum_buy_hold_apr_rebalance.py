"""
Momentum Buy-and-Hold CSV Generator (April Rebalance)
=====================================================
Based on: Momentum daily_april_rebalance.ipynb

Generates a buy_hold_csv file starting from 1st November 2025
with starting total_portfolio_value / NAV = 100.

Pipeline:
  1. Load momentum stock selections from master_momentum_summary.xlsx
  2. Fetch equity and GOLDBEES price data via TrueData
  3. Process equity leg (75) and initial GOLDBEES leg (25)
  4. Remove GOLDBEES after 2025-11-30 and build a rebalanced hedge book:
       - Dec 2025 – Jan 2026: GOLDBEES 60% / SILVERBEES 20% / MOGSEC 20%
       - Feb 2026:            GOLDBEES 40% / MOGSEC 60%
       - Mar 2026 onward:     GOLDBEES (carry) / LIQUIDCASE (carry from MOGSEC)
  5. Concatenate equity + hedge into final dataframe and export as CSV
"""

import numpy as np
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
import warnings
warnings.filterwarnings('ignore')
import time
import logging
from truedata import TD_hist
import os

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════
START_DATE = '2025-11-01'
INITIAL_NAV = 100.0
EQUITY_ALLOCATION = 75.0
HEDGE_ALLOCATION = 25.0
INPUT_FILE = "Stocks/Nifty_500_2025_Apr_20_stocks_results/master_momentum_summary.xlsx"
OUTPUT_FILE = "buy_hold_csv.csv"

# ═══════════════════════════════════════════════════════════════════════════════
# TrueData Helper
# ═══════════════════════════════════════════════════════════════════════════════

def fetch_truedata_history(
    ticker_list: list,
    duration: str = '2 Y',
    bar_size: str = 'EOD',
    sleep_time: float = 0.1
) -> tuple[pd.DataFrame, list]:
    """
    Fetches historical data from TrueData for a list of tickers.

    Returns
    -------
    final_df : pd.DataFrame
        Combined DataFrame of all tickers' historical data.
    error_list : list
        List of tickers that failed to fetch.
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


# ═══════════════════════════════════════════════════════════════════════════════
# Portfolio Processing  (matches notebook cell 3)
# ═══════════════════════════════════════════════════════════════════════════════

def process_portfolio(nav_df, ticker_data, initial_value=75, inception_date=None, output_file=None):
    """
    Process portfolio allocation with month-by-month rebalancing.

    Parameters
    ----------
    nav_df : pd.DataFrame
        Dataframe with at least ['Date', 'Year-Month', 'Ticker'] columns.
    ticker_data : pd.DataFrame
        Historical OHLC data with ['Date', 'Ticker', 'Close'].
    initial_value : float
        Initial portfolio allocation value.
    inception_date : str or pd.Timestamp or None
        Start date from which holdings should be valued.
    output_file : str or None
        If provided, saves the final dataframe to Excel.

    Returns
    -------
    pd.DataFrame
        Final dataframe with portfolio values.
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

    for year_month in nav_df['Year-Month'].drop_duplicates():
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
        stock_data['%change'] = stock_data.groupby('Ticker')['Close'].pct_change()

        stock_data_flt = stock_data[
            (stock_data['Date'] >= curr_month_start) & (stock_data['Date'] <= curr_month_end)
        ].copy()
        if stock_data_flt.empty:
            continue

        if not last_month_value:
            allocation_per_stock = initial_value / len(tickers)
            stock_allocations = {ticker: allocation_per_stock for ticker in tickers}
        else:
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
            ticker_df = stock_data_flt.loc[ticker_index].copy()
            if ticker_df.empty:
                continue

            stock_data_flt.loc[ticker_index, 'Initial_Allocation'] = init_value
            stock_data_flt.loc[ticker_index, 'Selection_Date'] = selection_date
            stock_data_flt.loc[ticker_index, 'Buy_Hold_Value'] = init_value * (
                (1 + stock_data_flt.loc[ticker_index, '%change'].fillna(0)).cumprod()
            )

            buy_price = float(ticker_df.iloc[0]['Close'])
            quantity = last_month_quantity.get(ticker, init_value / buy_price if buy_price else 0.0)
            stock_data_flt.loc[ticker_index, 'Buy_Price'] = buy_price
            stock_data_flt.loc[ticker_index, 'Quantity'] = quantity
            if 'Real_Rank' in month_nav.columns:
                rank_vals = month_nav.loc[month_nav['Ticker'] == ticker, 'Real_Rank']
                if not rank_vals.empty:
                    stock_data_flt.loc[ticker_index, 'Real_Rank'] = rank_vals.iloc[0]

        last_month_quantity = stock_data_flt.groupby('Ticker')['Quantity'].last().to_dict()
        last_month_value = stock_data_flt.groupby('Ticker')['Buy_Hold_Value'].last().to_dict()
        stock_data_flt['Total_Portfolio_Value'] = stock_data_flt.groupby('Date')['Buy_Hold_Value'].transform('sum')
        df_lis.append(stock_data_flt)

    final_df = pd.concat(df_lis, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)

    if output_file:
        final_df.to_excel(output_file, index=False)

    return final_df


# ═══════════════════════════════════════════════════════════════════════════════
# Hedge Segment Builder  (matches notebook cell 3)
# ═══════════════════════════════════════════════════════════════════════════════

def build_weighted_hedge_segment(hedge_prices, start_date, end_date, base_values, segment_name):
    """Build a single hedge segment with weighted allocations."""
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


def build_rebalanced_hedge_book(base_portfolio_df, hedge_prices, portfolio_end_date=None, default_hedge_value=25.0):
    """
    Build the multi-segment rebalanced hedge book (Dec/Jan -> Feb -> Mar onward).

    Parameters
    ----------
    base_portfolio_df : pd.DataFrame
        The equity + initial GOLDBEES portfolio (used to read the GOLDBEES
        ending value on 2025-11-30 as the hedge seed).
    hedge_prices : pd.DataFrame
        Pre-fetched OHLC data for GOLDBEES, SILVERBEES, MOGSEC, LIQUIDCASE.
    portfolio_end_date : pd.Timestamp or None
        Last date of the portfolio.
    default_hedge_value : float
        Fallback seed if GOLDBEES data is unavailable.

    Returns
    -------
    pd.DataFrame  (empty if portfolio hasn't reached Dec 2025)
    """
    if portfolio_end_date is None:
        portfolio_end_date = pd.to_datetime(base_portfolio_df['Date']).max()
    else:
        portfolio_end_date = pd.to_datetime(portfolio_end_date)

    cutoff_date = pd.Timestamp('2025-11-30')
    if portfolio_end_date <= cutoff_date:
        return pd.DataFrame()

    # Determine hedge seed from last GOLDBEES value on or before cutoff
    hedge_start_factor = base_portfolio_df[
        (base_portfolio_df['Ticker'] == 'GOLDBEES') & (base_portfolio_df['Date'] <= cutoff_date)
    ].sort_values('Date')
    hedge_seed = float(hedge_start_factor['Buy_Hold_Value'].iloc[-1]) if not hedge_start_factor.empty else default_hedge_value

    segments = []

    # --- Segment 1: Dec 2025 to Jan 2026 (60% GOLDBEES / 20% SILVERBEES / 20% MOGSEC) ---
    decjan_start = pd.Timestamp('2025-12-01')
    decjan_end = min(pd.Timestamp('2026-01-31'), portfolio_end_date)
    df_decjan = pd.DataFrame()
    if portfolio_end_date >= decjan_start:
        decjan_values = {
            'GOLDBEES':    0.60 * hedge_seed,
            'SILVERBEES':  0.20 * hedge_seed,
            'MOGSEC':      0.20 * hedge_seed
        }
        df_decjan = build_weighted_hedge_segment(hedge_prices, decjan_start, decjan_end, decjan_values, '2025-12_to_2026-01')
        if not df_decjan.empty:
            segments.append(df_decjan)

    # --- Segment 2: Feb 2026 (40% GOLDBEES / 60% MOGSEC) ---
    feb_start = pd.Timestamp('2026-02-01')
    feb_end = min(pd.Timestamp('2026-02-28'), portfolio_end_date)
    df_feb = pd.DataFrame()
    if portfolio_end_date >= feb_start and not df_decjan.empty:
        feb_factor = (
            df_decjan.groupby('Date', as_index=False)['Buy_Hold_Value']
            .sum().sort_values('Date')['Buy_Hold_Value'].iloc[-1]
        )
        feb_values = {'GOLDBEES': 0.40 * feb_factor, 'MOGSEC': 0.60 * feb_factor}
        df_feb = build_weighted_hedge_segment(hedge_prices, feb_start, feb_end, feb_values, '2026-02')
        if not df_feb.empty:
            segments.append(df_feb)

    # --- Segment 3: Mar 2026 onward (GOLDBEES carry / LIQUIDCASE from MOGSEC) ---
    mar_start = pd.Timestamp('2026-03-01')
    if portfolio_end_date >= mar_start and not df_feb.empty:
        feb_last_date = df_feb['Date'].max()
        feb_last = df_feb[df_feb['Date'] == feb_last_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
        mar_values = {
            'GOLDBEES':   feb_last.get('GOLDBEES', 0.0),
            'LIQUIDCASE': feb_last.get('MOGSEC', 0.0)
        }
        df_mar = build_weighted_hedge_segment(hedge_prices, mar_start, portfolio_end_date, mar_values, '2026-03_onward')
        if not df_mar.empty:
            segments.append(df_mar)

    if not segments:
        return pd.DataFrame()

    return pd.concat(segments, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print(f"{'='*60}")
    print(f"  Momentum Buy-Hold CSV Generator (April Rebalance)")
    print(f"  Start Date : {START_DATE}")
    print(f"  Initial NAV: {INITIAL_NAV}")
    print(f"{'='*60}\n")

    # ── 1. Load Momentum Selections ──────────────────────────────────────────
    nav_df_raw = pd.read_excel(INPUT_FILE).rename(columns={'End_Date': 'Date'})
    nav_df_raw['Date'] = pd.to_datetime(nav_df_raw['Date'])

    end_date_str = date.today().strftime('%Y-%m-%d')

    selected_cols = ['Date', 'Ticker']
    if 'Real_Rank' in nav_df_raw.columns:
        selected_cols.append('Real_Rank')

    nav_df = (
        nav_df_raw[(nav_df_raw['Date'] >= START_DATE) & (nav_df_raw['Date'] <= end_date_str)]
        .reset_index(drop=True)[selected_cols]
    )
    nav_df['Year-Month'] = nav_df['Date'].dt.to_period('M').astype(str)

    # ── 2. Add GOLDBEES as the initial hedge leg ─────────────────────────────
    goldbees_df = pd.DataFrame({
        'Date': nav_df['Date'].drop_duplicates().sort_values(),
        'Ticker': 'GOLDBEES'
    })
    if 'Real_Rank' in nav_df.columns:
        goldbees_df['Real_Rank'] = np.nan
    goldbees_df['Year-Month'] = pd.to_datetime(goldbees_df['Date']).dt.to_period('M').astype(str)

    concat_df = (
        pd.concat([nav_df, goldbees_df], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )

    # ── 3. Fetch Equity Data ─────────────────────────────────────────────────
    ticker_df = concat_df.query("Ticker != 'GOLDBEES'")
    symbol_list = ticker_df['Ticker'].unique()
    print(f"Fetching data for {len(symbol_list)} equity tickers...")
    ticker_data_other_stocks, _ = fetch_truedata_history(
        ticker_list=symbol_list,
        duration='10 Y',
        bar_size='EOD',
        sleep_time=0.1
    )

    # ── 4. Fetch Gold Data ───────────────────────────────────────────────────
    gold_df = concat_df.query("Ticker == 'GOLDBEES'")
    print("Fetching data for GOLDBEES...")
    ticker_data_gold, _ = fetch_truedata_history(
        ticker_list=gold_df['Ticker'].unique(),
        duration='10 Y',
        bar_size='EOD',
        sleep_time=0.1
    )

    # ── 5. Process Equity and Initial Gold Legs ──────────────────────────────
    inception_dt = pd.to_datetime(START_DATE)
    print("Processing Equity leg...")
    final_df_equity = process_portfolio(
        ticker_df, ticker_data_other_stocks,
        EQUITY_ALLOCATION, inception_date=inception_dt
    )
    print("Processing Initial GOLDBEES leg...")
    final_df_gold = process_portfolio(
        gold_df, ticker_data_gold,
        HEDGE_ALLOCATION, inception_date=inception_dt
    )

    # ── 6. Combine equity + initial gold ─────────────────────────────────────
    final_df = (
        pd.concat([final_df_equity, final_df_gold], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )

    # ── 7. Strip GOLDBEES after 2025-11-30 (will be replaced by hedge book) ─
    old_df = final_df[~((final_df['Date'] > '2025-11-30') & (final_df['Ticker'] == 'GOLDBEES'))]

    # ── 8. Build Rebalanced Hedge Book ───────────────────────────────────────
    portfolio_end_date = pd.to_datetime(final_df['Date']).max()
    print("Fetching hedge ticker data (GOLDBEES, SILVERBEES, MOGSEC, LIQUIDCASE)...")
    hedge_prices, _ = fetch_truedata_history(
        ticker_list=['GOLDBEES', 'SILVERBEES', 'MOGSEC', 'LIQUIDCASE'],
        duration='5 Y',
        bar_size='EOD',
        sleep_time=0.1
    )
    print("Building rebalanced hedge book...")
    hedge_df = build_rebalanced_hedge_book(
        base_portfolio_df=final_df,
        hedge_prices=hedge_prices,
        portfolio_end_date=portfolio_end_date,
        default_hedge_value=HEDGE_ALLOCATION
    )

    # ── 9. Final Merge ───────────────────────────────────────────────────────
    conc_df = pd.concat([old_df, hedge_df], ignore_index=True)
    conc_df = conc_df.sort_values(['Date', 'Ticker']).reset_index(drop=True)

    # ── 10. Export to CSV ────────────────────────────────────────────────────
    conc_df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n✅ Success! Portfolio exported to: {OUTPUT_FILE}")

    # ── 11. Verify starting NAV ──────────────────────────────────────────────
    start_date_actual = conc_df['Date'].min()
    start_nav = conc_df[conc_df['Date'] == start_date_actual]['Buy_Hold_Value'].sum()
    end_date_actual = conc_df['Date'].max()
    end_nav = conc_df[conc_df['Date'] == end_date_actual]['Buy_Hold_Value'].sum()

    print(f"\n{'─'*40}")
    print(f"  Starting Date : {start_date_actual}")
    print(f"  Starting NAV  : {start_nav:.2f}")
    print(f"  Ending Date   : {end_date_actual}")
    print(f"  Ending NAV    : {end_nav:.2f}")
    print(f"{'─'*40}")


if __name__ == "__main__":
    main()
