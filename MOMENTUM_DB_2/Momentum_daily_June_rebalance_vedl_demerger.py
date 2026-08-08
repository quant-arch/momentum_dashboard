"""
Momentum_daily_June_rebalance_vedl_demerger.py
===============================================
Converted from: Momentum daily_June_rebalance.ipynb

VEDL Demerger Adjustment Logic
-------------------------------
TrueData has retroactively adjusted VEDL prices to reflect the demerger
(current fetched prices = 52.34% of original consolidated price).

This script:
  1. Restores VEDL to its consolidated (pre-demerger) price for all dates
     up to and including 2026-06-15  →  price × (100 / 52.34)
  2. On 2026-06-15, splits VEDL's consolidated Buy_Hold_Value into 5 new
     entities per the court-approved demerger ratios:
       VEDL     52.34%  (Vedanta Limited residual)
       VAML      7.15%  (Vedanta Aluminium Metal Ltd)
       VISL      6.79%  (Vedanta Iron and Steel Ltd)
       VEDPOWER 12.23%  (Talwandi Sabo Power Ltd)
       VOGL     21.49%  (Malco Energy Ltd)
  3. Tracks each entity independently after demerger using their live
     TrueData prices (all confirmed present: VEDL, VAML, VISL, VEDPOWER, VOGL)
  4. Writes a SEPARATE output file:
       Trials/VEDL_demerger_adjusted_buy_hold_returns.xlsx

All original output files are left untouched.
"""

# ============================================================
# 0.  IMPORTS
# ============================================================
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import pyodbc
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import time
import logging
import requests
import sys, os

sys.path.insert(0, r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2")
from truedata_connector import get_td_obj

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============================================================
# 1.  VEDL DEMERGER CONSTANTS
# ============================================================
VEDL_DEMERGER_DATE    = pd.Timestamp('2026-06-14')   # last consolidated trading day was before 15th
VEDL_ADJ_FACTOR       = 100.0 / 52.34               # ≈ 1.9106  (restores consolidated price)

# Ratios per the NCLT/court-approved demerger scheme
DEMERGER_RATIOS = {
    'VEDL':     0.5234,   # Vedanta Limited (residual)
    'VAML':     0.0715,   # Vedanta Aluminium Metal Ltd
    'VISL':     0.0679,   # Vedanta Iron and Steel Ltd
    'VEDPOWER': 0.1223,   # Talwandi Sabo Power Ltd
    'VOGL':     0.2149,   # Malco Energy Ltd
}

# ============================================================
# 2.  TRUEDATA FETCH HELPER
# ============================================================
def fetch_truedata_history(
    ticker_list: list,
    duration: str = '1 Y',
    bar_size: str = 'EOD',
    sleep_time: float = 0.1,
    max_retries: int = 5,
) -> tuple:
    """
    Fetches historical data from TrueData with auto-reconnect on IP/session drops.
    Drop-in replacement for the original fetch_truedata_history.
    """
    td_hist = get_td_obj()
    df_list = []
    error_list = []

    for ticker in ticker_list:
        fetched = False
        for attempt in range(1, max_retries + 1):
            try:
                df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)

                if df is None or (hasattr(df, 'empty') and df.empty):
                    logging.warning(f'No data fetched for {ticker}')
                    error_list.append(ticker)
                    fetched = True
                    break

                df['Ticker'] = ticker

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

                df_list.append(df)
                logging.info(f"Fetched data for {ticker} ({len(df)} rows).")
                fetched = True
                break

            except Exception as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logging.warning(f"[{ticker}] Attempt {attempt}/{max_retries} failed: {e}. "
                                    f"Reconnecting in {wait}s...")
                    time.sleep(wait)
                    try:
                        td_hist = get_td_obj(force_reconnect=True)
                    except Exception as ce:
                        logging.error(f"Reconnect failed: {ce}")
                else:
                    logging.error(f"All {max_retries} attempts failed for {ticker}: {e}")

        if not fetched:
            error_list.append(ticker)

        time.sleep(sleep_time)

    final_df = pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()
    return final_df, error_list


# ============================================================
# 3.  PORTFOLIO PROCESSING FUNCTIONS  (unchanged from notebook)
# ============================================================
def process_portfolio(nav_df, ticker_data, initial_value=75, inception_date=None, output_file=None):
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

    for year_month in nav_df['Year-Month'].drop_duplicates():
        month_nav = nav_df[nav_df['Year-Month'] == year_month].copy()
        tickers = month_nav['Ticker'].dropna().unique().tolist()
        selection_date = pd.to_datetime(month_nav['Date'].min())
        year_month_date = pd.to_datetime(f"{year_month}-01")

        prev_month_start = year_month_date - relativedelta(months=2)
        curr_month_start = year_month_date
        curr_month_end   = year_month_date + pd.offsets.MonthEnd(0)

        stock_data = ticker_data[
            (ticker_data['Date'] >= prev_month_start)
            & (ticker_data['Date'] <= curr_month_end)
            & (ticker_data['Ticker'].isin(tickers))
        ].copy()
        stock_data = stock_data[stock_data['Date'] >= inception_date].copy()
        stock_data['%change'] = stock_data.groupby('Ticker')['Close'].pct_change().fillna(
            stock_data['Close'] / stock_data['Open'] - 1
        )

        stock_data_flt = stock_data[
            (stock_data['Date'] >= curr_month_start) & (stock_data['Date'] <= curr_month_end)
        ].copy()
        if stock_data_flt.empty:
            continue

        if not last_month_value:
            allocation_per_stock = initial_value / len(tickers)
            stock_allocations = {ticker: allocation_per_stock for ticker in tickers}
        else:
            stock_allocations = {ticker: last_month_value[ticker]
                                 for ticker in tickers if ticker in last_month_value}
            dropped_stocks = [ticker for ticker in last_month_value if ticker not in tickers]
            dropped_value  = sum(last_month_value[ticker] for ticker in dropped_stocks)
            new_stocks     = [ticker for ticker in tickers if ticker not in last_month_value]
            if new_stocks:
                allocation_per_stock = dropped_value / len(new_stocks) if dropped_value else 0.0
                for ticker in new_stocks:
                    stock_allocations[ticker] = allocation_per_stock
                    ticker_idx = stock_data_flt[stock_data_flt['Ticker'] == ticker].index
                    if not ticker_idx.empty:
                        f_idx = ticker_idx[0]
                        open_px  = stock_data_flt.loc[f_idx, 'Open']
                        close_px = stock_data_flt.loc[f_idx, 'Close']
                        if open_px and open_px > 0:
                            stock_data_flt.loc[f_idx, '%change'] = (close_px / open_px) - 1

        for ticker, init_value in stock_allocations.items():
            ticker_index = stock_data_flt[stock_data_flt['Ticker'] == ticker].index
            ticker_df    = stock_data_flt.loc[ticker_index].copy()
            if ticker_df.empty:
                continue

            stock_data_flt.loc[ticker_index, 'Initial_Allocation'] = init_value
            stock_data_flt.loc[ticker_index, 'Selection_Date']     = selection_date
            stock_data_flt.loc[ticker_index, 'Buy_Hold_Value']     = init_value * (
                (1 + stock_data_flt.loc[ticker_index, '%change'].fillna(0)).cumprod()
            )

            buy_price = float(ticker_df.iloc[0]['Close'])
            quantity  = last_month_quantity.get(ticker, init_value / buy_price if buy_price else 0.0)
            stock_data_flt.loc[ticker_index, 'Buy_Price'] = buy_price
            stock_data_flt.loc[ticker_index, 'Quantity']  = quantity
            if 'Real_Rank' in month_nav.columns:
                stock_data_flt.loc[ticker_index, 'Real_Rank'] = \
                    month_nav.loc[month_nav['Ticker'] == ticker, 'Real_Rank'].iloc[0]

        last_month_quantity = stock_data_flt.groupby('Ticker')['Quantity'].last().to_dict()
        last_month_value    = stock_data_flt.groupby('Ticker')['Buy_Hold_Value'].last().to_dict()
        stock_data_flt['Total_Portfolio_Value'] = \
            stock_data_flt.groupby('Date')['Buy_Hold_Value'].transform('sum')
        df_lis.append(stock_data_flt)

    final_df = pd.concat(df_lis, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)

    if output_file:
        final_df.to_excel(output_file, index=False)

    return final_df


def build_weighted_hedge_segment(hedge_prices, start_date, end_date, base_values, segment_name,
                                  new_tickers=None):
    """
    new_tickers: list of tickers entering this segment fresh (bought at Open on Day 1).
                 All others are assumed to be continuing (overnight close-to-close on Day 1).
    """
    if new_tickers is None:
        new_tickers = []

    segment = hedge_prices[
        (hedge_prices['Date'] >= start_date)
        & (hedge_prices['Date'] <= end_date)
        & (hedge_prices['Ticker'].isin(base_values))
    ][['Date', 'Ticker', 'Open', 'Close']].copy()
    if segment.empty:
        return segment

    segment = segment.sort_values(['Ticker', 'Date'])

    full_history = hedge_prices[
        hedge_prices['Ticker'].isin(base_values)
    ][['Date', 'Ticker', 'Close']].sort_values(['Ticker', 'Date']).copy()
    full_history['%change_full'] = full_history.groupby('Ticker')['Close'].pct_change()

    segment = segment.merge(
        full_history[['Date', 'Ticker', '%change_full']],
        on=['Date', 'Ticker'],
        how='left'
    )

    segment['%change'] = segment['%change_full']

    for ticker in new_tickers:
        mask = (segment['Ticker'] == ticker) & (segment['Date'] == start_date)
        if mask.any():
            segment.loc[mask, '%change'] = \
                (segment.loc[mask, 'Close'] / segment.loc[mask, 'Open']) - 1

    day1_mask = segment['Date'] == start_date
    segment.loc[day1_mask & segment['%change'].isna(), '%change'] = (
        segment.loc[day1_mask & segment['%change'].isna(), 'Close'] /
        segment.loc[day1_mask & segment['%change'].isna(), 'Open'] - 1
    )

    segment = segment.drop(columns=['%change_full'])
    segment['Initial_Allocation'] = segment['Ticker'].map(base_values)
    segment['ret_factor']         = 1 + segment['%change'].fillna(0)
    segment['cum_factor']         = segment.groupby('Ticker')['ret_factor'].cumprod()
    segment['Buy_Hold_Value']     = segment['Initial_Allocation'] * segment['cum_factor']

    buy_prices             = segment.groupby('Ticker')['Close'].transform('first')
    segment['Buy_Price']  = buy_prices
    segment['Quantity']   = np.where(buy_prices > 0, segment['Initial_Allocation'] / buy_prices, 0.0)
    segment['Selection_Date']        = start_date
    segment['Hedge_Segment']         = segment_name
    segment['Total_Portfolio_Value'] = segment.groupby('Date')['Buy_Hold_Value'].transform('sum')
    return segment.drop(columns=['ret_factor', 'cum_factor'])


def build_rebalanced_hedge_book(base_portfolio_df, portfolio_end_date=None, default_hedge_value=25.0):
    if portfolio_end_date is None:
        portfolio_end_date = pd.to_datetime(base_portfolio_df['Date']).max()
    else:
        portfolio_end_date = pd.to_datetime(portfolio_end_date)

    cutoff_date = pd.Timestamp('2025-11-30')
    if portfolio_end_date <= cutoff_date:
        return pd.DataFrame()

    hedge_start_factor = base_portfolio_df[
        (base_portfolio_df['Ticker'] == 'GOLDBEES') & (base_portfolio_df['Date'] <= cutoff_date)
    ].sort_values('Date')
    hedge_seed = float(hedge_start_factor['Buy_Hold_Value'].iloc[-1]) \
        if not hedge_start_factor.empty else default_hedge_value

    hedge_prices = fetch_truedata_history(
        ticker_list=['GOLDBEES', 'SILVERBEES', 'MOGSEC', 'LIQUIDCASE', 'CPSEETF', 'PHARMABEES', 'NEXT50IETF'],
        duration='5 Y',
        bar_size='EOD',
        sleep_time=0.1
    )[0]

    segments = []

    # December → January segment
    decjan_start = pd.Timestamp('2025-12-01')
    decjan_end   = min(pd.Timestamp('2026-01-31'), portfolio_end_date)
    if portfolio_end_date >= decjan_start:
        decjan_values = {
            'GOLDBEES': 0.60 * hedge_seed,
            'SILVERBEES': 0.20 * hedge_seed,
            'MOGSEC': 0.20 * hedge_seed
        }
        df_decjan = build_weighted_hedge_segment(
            hedge_prices, start_date=decjan_start, end_date=decjan_end,
            base_values=decjan_values, segment_name='2025-12_to_2026-01'
        )
        if not df_decjan.empty:
            segments.append(df_decjan)
        else:
            df_decjan = pd.DataFrame()
    else:
        df_decjan = pd.DataFrame()

    # February segment
    feb_start = pd.Timestamp('2026-02-01')
    feb_end   = min(pd.Timestamp('2026-02-28'), portfolio_end_date)
    if portfolio_end_date >= feb_start and not df_decjan.empty:
        feb_factor = df_decjan.groupby('Date', as_index=False)['Buy_Hold_Value'].sum() \
                               .sort_values('Date')['Buy_Hold_Value'].iloc[-1]
        feb_values = {'GOLDBEES': 0.40 * feb_factor, 'MOGSEC': 0.60 * feb_factor}
        df_feb = build_weighted_hedge_segment(
            hedge_prices, start_date=feb_start, end_date=feb_end,
            base_values=feb_values, segment_name='2026-02'
        )
        if not df_feb.empty:
            segments.append(df_feb)
        else:
            df_feb = pd.DataFrame()
    else:
        df_feb = pd.DataFrame()

    # March → April segment
    mar_start = pd.Timestamp('2026-03-01')
    mar_end   = min(pd.Timestamp('2026-04-30'), portfolio_end_date)
    df_mar    = pd.DataFrame()
    if portfolio_end_date >= mar_start and not df_feb.empty:
        feb_last_date = df_feb['Date'].max()
        feb_last      = df_feb[df_feb['Date'] == feb_last_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
        mar_values    = {
            'GOLDBEES':    feb_last.get('GOLDBEES', 0.0),
            'LIQUIDCASE':  feb_last.get('MOGSEC', 0.0)
        }
        df_mar = build_weighted_hedge_segment(
            hedge_prices, start_date=mar_start, end_date=mar_end,
            base_values=mar_values,
            segment_name='2026-03_to_2026-04' if portfolio_end_date >= mar_end else '2026-03_onward',
            new_tickers=['LIQUIDCASE']
        )
        if not df_mar.empty:
            segments.append(df_mar)

    # May segment
    may_start = pd.Timestamp('2026-05-01')
    may_end   = min(pd.Timestamp('2026-05-31'), portfolio_end_date)
    df_may    = pd.DataFrame()
    if portfolio_end_date >= may_start and not df_mar.empty:
        mar_last_date      = df_mar['Date'].max()
        mar_last           = df_mar[df_mar['Date'] == mar_last_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
        total_hedge_value  = sum(mar_last.values())
        may_values = {
            'GOLDBEES':   0.20 * total_hedge_value,
            'LIQUIDCASE': 0.40 * total_hedge_value,
            'CPSEETF':    0.20 * total_hedge_value,
            'NEXT50IETF': 0.20 * total_hedge_value,
        }
        df_may = build_weighted_hedge_segment(
            hedge_prices, start_date=may_start, end_date=may_end,
            base_values=may_values, segment_name='2026-05'
        )
        if not df_may.empty:
            segments.append(df_may)

    # June: sell CPSEETF → buy PHARMABEES
    june_start = pd.Timestamp('2026-06-01')
    df_june    = pd.DataFrame()
    if portfolio_end_date >= june_start:
        cpse_value      = 0.0
        source_snapshot = None
        if 'df_may' in locals() and not df_may.empty and 'CPSEETF' in df_may['Ticker'].unique():
            snap_date       = df_may['Date'].max()
            source_snapshot = df_may[df_may['Date'] == snap_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
            cpse_value      = source_snapshot.get('CPSEETF', 0.0)
        elif 'df_mar' in locals() and not df_mar.empty and 'CPSEETF' in df_mar['Ticker'].unique():
            snap_date       = df_mar['Date'].max()
            source_snapshot = df_mar[df_mar['Date'] == snap_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
            cpse_value      = source_snapshot.get('CPSEETF', 0.0)

        if cpse_value > 0.0:
            june_values              = {k: v for k, v in source_snapshot.items() if k != 'CPSEETF'}
            june_values['PHARMABEES'] = june_values.get('PHARMABEES', 0.0) + cpse_value

            df_june = build_weighted_hedge_segment(
                hedge_prices, start_date=june_start, end_date=portfolio_end_date,
                base_values=june_values, segment_name='2026-06_onward',
                new_tickers=['PHARMABEES']
            )

            if not df_june.empty:
                hc_prices = hedge_prices[
                    (hedge_prices['Ticker'] == 'PHARMABEES') & (hedge_prices['Date'] >= june_start)
                ].sort_values('Date')
                hc_open = float(hc_prices.iloc[0]['Open']) if not hc_prices.empty else None

                hc_mask = df_june['Ticker'] == 'PHARMABEES'
                if hc_mask.any() and hc_open:
                    df_june.loc[hc_mask, 'Buy_Price'] = hc_open
                    df_june.loc[hc_mask, 'Quantity']  = np.where(
                        hc_open > 0, df_june.loc[hc_mask, 'Initial_Allocation'] / hc_open, 0.0
                    )
                    df_june.loc[hc_mask, 'Buy_Hold_Value'] = df_june.loc[hc_mask, 'Initial_Allocation'] * (
                        (1 + df_june.loc[hc_mask, '%change'].fillna(0))
                        .groupby(df_june.loc[hc_mask, 'Ticker']).cumprod()
                    )

                df_june = df_june[df_june['Ticker'] != 'CPSEETF']
                segments.append(df_june)

    if not segments:
        return pd.DataFrame()

    hedge_book = pd.concat(segments, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)
    return hedge_book


# ============================================================
# 4.  PREPARE & PROCESS  (with VEDL consolidation hook)
# ============================================================
def apply_vedl_consolidation(ticker_data: pd.DataFrame) -> pd.DataFrame:
    """
    For all VEDL rows with Date <= VEDL_DEMERGER_DATE, multiply OHLC
    by VEDL_ADJ_FACTOR to restore the pre-demerger consolidated price.
    TrueData has retroactively compressed VEDL prices to 52.34% of
    the original; this reverses that adjustment.
    """
    mask = (ticker_data['Ticker'] == 'VEDL') & \
           (pd.to_datetime(ticker_data['Date']) <= VEDL_DEMERGER_DATE)
    price_cols = [c for c in ['Open', 'High', 'Low', 'Close'] if c in ticker_data.columns]
    ticker_data = ticker_data.copy()
    for col in price_cols:
        ticker_data.loc[mask, col] = ticker_data.loc[mask, col] * VEDL_ADJ_FACTOR
    n = mask.sum()
    logging.info(f"[VEDL Consolidation] Applied factor {VEDL_ADJ_FACTOR:.6f} to {n} VEDL rows "
                 f"(dates <= {VEDL_DEMERGER_DATE.date()})")
    return ticker_data


def prepare_and_process_portfolio(input_file, start_date, end_date, output_folder,
                                  process_portfolio_fn,
                                  equity_allocation=75, gold_allocation=25,
                                  apply_vedl_adj=False):
    """
    Prepare portfolio dataframe with momentum stocks + GOLDBEES and process performance.
    If apply_vedl_adj=True, applies VEDL consolidated-price correction before compounding.
    """
    nav_df_raw = pd.read_excel(input_file).rename(columns={'End_Date': 'Date'})
    nav_df_raw['Date'] = pd.to_datetime(nav_df_raw['Date'])

    selected_cols = ['Date', 'Ticker']
    if 'Real_Rank' in nav_df_raw.columns:
        selected_cols.append('Real_Rank')

    nav_df = (
        nav_df_raw[(nav_df_raw['Date'] >= start_date) & (nav_df_raw['Date'] <= end_date)]
        .reset_index(drop=True)[selected_cols]
    )
    nav_df['Year-Month'] = nav_df['Date'].dt.to_period('M').astype(str)

    goldbees_df = pd.DataFrame({
        'Date':   nav_df['Date'].drop_duplicates().sort_values(),
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

    # --- Equity leg ---
    ticker_df  = concat_df.query("Ticker != 'GOLDBEES'")
    symbol_list = ticker_df['Ticker'].unique()
    ticker_data_other_stocks, errors_other = fetch_truedata_history(
        ticker_list=symbol_list, duration='10 Y', bar_size='EOD', sleep_time=0.1
    )
    if errors_other:
        logging.warning(f'Failed to fetch data for {errors_other}')

    # Apply VEDL consolidation BEFORE compounding
    if apply_vedl_adj:
        ticker_data_other_stocks = apply_vedl_consolidation(ticker_data_other_stocks)

    # --- Gold leg ---
    gold_df     = concat_df.query("Ticker == 'GOLDBEES'")
    symbol_list = gold_df['Ticker'].unique()
    ticker_data_gold, errors_gold = fetch_truedata_history(
        ticker_list=symbol_list, duration='10 Y', bar_size='EOD', sleep_time=0.1
    )
    if errors_gold:
        logging.warning(f'Failed to fetch gold data for {errors_gold}')

    inception_date = pd.to_datetime(start_date)

    final_df_other_stocks = process_portfolio_fn(
        ticker_df, ticker_data_other_stocks, equity_allocation, inception_date=inception_date
    )
    final_df_gold = process_portfolio_fn(
        gold_df, ticker_data_gold, gold_allocation, inception_date=inception_date
    )

    final_df = (
        pd.concat([final_df_other_stocks, final_df_gold], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    middle_folder = os.path.basename(os.path.dirname(input_file))
    output_file   = os.path.join(output_folder, f"{middle_folder}_gold_buy&hold_returns.xlsx")
    print(f"Final output path: {output_file}")

    return final_df


# ============================================================
# 5.  VEDL DEMERGER SEGMENT BUILDER
# ============================================================
def build_vedl_demerger_segment(conc_df: pd.DataFrame,
                                 post_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Reads VEDL's last consolidated Buy_Hold_Value (on or before VEDL_DEMERGER_DATE)
    from the already-processed conc_df, seeds 5 entities using DEMERGER_RATIOS,
    and builds a Buy_Hold segment for the post-demerger period.

    All 5 entities are treated as NEW (bought at Open on first trading day after
    VEDL_DEMERGER_DATE) so there is no artificial price-gap return on day 1.
    """
    # ------------------------------------------------------------------
    # Step 1: Find VEDL's last consolidated BHV
    # ------------------------------------------------------------------
    vedl_rows = conc_df[
        (conc_df['Ticker'] == 'VEDL') &
        (pd.to_datetime(conc_df['Date']) <= VEDL_DEMERGER_DATE)
    ].sort_values('Date')

    if vedl_rows.empty:
        logging.error("No VEDL rows found on or before demerger date — skipping demerger segment.")
        return pd.DataFrame()

    last_vedl_date  = vedl_rows['Date'].max()
    last_vedl_bhv   = float(vedl_rows[vedl_rows['Date'] == last_vedl_date]['Buy_Hold_Value'].iloc[-1])

    logging.info(f"[Demerger] VEDL last consolidated BHV on {last_vedl_date.date()}: "
                 f"{last_vedl_bhv:.4f}")

    # ------------------------------------------------------------------
    # Step 2: Seed each entity
    # ------------------------------------------------------------------
    base_values = {
        ticker: round(last_vedl_bhv * ratio, 6)
        for ticker, ratio in DEMERGER_RATIOS.items()
    }
    logging.info("[Demerger] Seeded allocations:")
    for t, v in base_values.items():
        logging.info(f"  {t:<10} {DEMERGER_RATIOS[t]*100:.2f}%  →  {v:.4f}")

    # ------------------------------------------------------------------
    # Step 3: Find first trading day after demerger date
    # ------------------------------------------------------------------
    post_prices = post_prices.copy()
    post_prices['Date'] = pd.to_datetime(post_prices['Date'])

    available_tickers = post_prices['Ticker'].unique().tolist()
    missing = [t for t in DEMERGER_RATIOS if t not in available_tickers]
    if missing:
        logging.warning(f"[Demerger] Missing tickers in post_prices: {missing} — they will be absent from output.")
        base_values = {k: v for k, v in base_values.items() if k in available_tickers}

    post_filtered = post_prices[post_prices['Date'] > VEDL_DEMERGER_DATE]
    if post_filtered.empty:
        logging.warning("[Demerger] No post-demerger price data available after demerger date.")
        return pd.DataFrame()

    post_start = post_filtered['Date'].min()
    post_end   = post_filtered['Date'].max()

    logging.info(f"[Demerger] Post-demerger segment: {post_start.date()} → {post_end.date()}")

    # ------------------------------------------------------------------
    # Step 4: Build the segment (all 5 are 'new' → Day-1 uses intraday return)
    # ------------------------------------------------------------------
    segment = build_weighted_hedge_segment(
        hedge_prices=post_prices,
        start_date=post_start,
        end_date=post_end,
        base_values=base_values,
        segment_name='VEDL_demerger_post_15Jun2026',
        new_tickers=list(base_values.keys()),   # all new on Day 1
    )

    if segment.empty:
        logging.warning("[Demerger] Demerger segment came back empty.")
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # Step 5: Override Buy_Price & Quantity for the exact requirements
    # ------------------------------------------------------------------
    # 1. For 4 new demerged entities: Buy_Price = Open price on 15th June 2026
    for ticker in ['VAML', 'VISL', 'VEDPOWER', 'VOGL']:
        mask = segment['Ticker'] == ticker
        if mask.any():
            first_open = float(segment[mask & (segment['Date'] == post_start)]['Open'].iloc[0])
            segment.loc[mask, 'Buy_Price'] = first_open
            # Also update Quantity = Initial_Allocation / Buy_Price
            segment.loc[mask, 'Quantity'] = np.where(first_open > 0, segment.loc[mask, 'Initial_Allocation'] / first_open, 0.0)

    # 2. For VEDL: Buy_Price = Unconsolidated Open price on its entry date into the portfolio
    vedl_entry_date = vedl_rows['Date'].min()
    vedl_entry_open_cons = float(vedl_rows[vedl_rows['Date'] == vedl_entry_date]['Open'].iloc[0])
    vedl_true_open = vedl_entry_open_cons / VEDL_ADJ_FACTOR

    mask_vedl = segment['Ticker'] == 'VEDL'
    if mask_vedl.any():
        segment.loc[mask_vedl, 'Buy_Price'] = vedl_true_open
        # We also update Quantity for VEDL so it aligns with its Initial Allocation in the segment
        segment.loc[mask_vedl, 'Quantity'] = np.where(vedl_true_open > 0, segment.loc[mask_vedl, 'Initial_Allocation'] / vedl_true_open, 0.0)

    # Tag the rows so they're easily identifiable in the output
    segment['Demerger_Entity'] = segment['Ticker'].map({
        'VEDL':     'Vedanta Ltd (residual)',
        'VAML':     'Vedanta Aluminium Metal Ltd',
        'VISL':     'Vedanta Iron and Steel Ltd',
        'VEDPOWER': 'Talwandi Sabo Power Ltd',
        'VOGL':     'Malco Energy Ltd',
    })

    logging.info(f"[Demerger] Built {len(segment)} post-demerger rows across "
                 f"{segment['Ticker'].nunique()} tickers.")
    return segment


# ============================================================
# 6.  MAIN EXECUTION
# ============================================================
def main():
    # ----------------------------------------------------------------
    # CONFIG — adjust paths here if needed
    # ----------------------------------------------------------------
    INPUT_FILE    = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results\master_momentum_summary.xlsx"
    START_DATE    = "2023-04-01"
    END_DATE      = date.today().strftime('%Y-%m-%d')
    OUTPUT_FOLDER = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials"

    # Demerger-adjusted output file
    VEDL_OUTPUT   = os.path.join(OUTPUT_FOLDER,
                                  "Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")

    # ----------------------------------------------------------------
    # STEP 1: Run the standard portfolio pipeline
    #         (with VEDL consolidation applied to ticker_data)
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 1: Running standard portfolio pipeline")
    print("  (VEDL prices restored to consolidated values)")
    print("="*65)

    final_df = prepare_and_process_portfolio(
        input_file=INPUT_FILE,
        start_date=START_DATE,
        end_date=END_DATE,
        output_folder=OUTPUT_FOLDER,
        process_portfolio_fn=process_portfolio,
        apply_vedl_adj=True,           # <-- key: restores VEDL consolidated prices
    )

    print(f"\nfinal_df shape: {final_df.shape}")

    # ----------------------------------------------------------------
    # STEP 2: Strip old GOLDBEES rows that are superseded by hedge book
    # ----------------------------------------------------------------
    old_df = final_df[
        ~((final_df['Date'] > '2025-11-30') & (final_df['Ticker'] == 'GOLDBEES'))
    ].copy()

    print(f"old_df shape (equity + pre-hedge gold): {old_df.shape}")

    # ----------------------------------------------------------------
    # STEP 3: Build hedge book (unchanged from notebook)
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 3: Building hedge book")
    print("="*65)

    portfolio_end_date = pd.to_datetime(final_df['Date']).max()
    hedge_df = build_rebalanced_hedge_book(
        base_portfolio_df=final_df,
        portfolio_end_date=portfolio_end_date,
        default_hedge_value=25.0
    )
    print(f"hedge_df shape: {hedge_df.shape}")

    # ----------------------------------------------------------------
    # STEP 4: Combine equity + hedge (same as notebook conc_df)
    # ----------------------------------------------------------------
    conc_df = pd.concat([old_df, hedge_df], ignore_index=True) \
                .sort_values(['Date', 'Ticker']).reset_index(drop=True)
    print(f"\nconc_df shape (before demerger adjustment): {conc_df.shape}")
    print(f"Unique tickers: {conc_df['Ticker'].nunique()}")

    # Verify VEDL consolidated prices look correct
    vedl_sample = conc_df[conc_df['Ticker'] == 'VEDL'].sort_values('Date')
    if not vedl_sample.empty:
        first_vedl = vedl_sample.iloc[0]
        last_vedl  = vedl_sample[vedl_sample['Date'] <= VEDL_DEMERGER_DATE].iloc[-1] \
                     if not vedl_sample[vedl_sample['Date'] <= VEDL_DEMERGER_DATE].empty \
                     else vedl_sample.iloc[-1]
        print(f"\nVEDL consolidated check:")
        print(f"  First row  {first_vedl['Date'].date()}  Close={first_vedl['Close']:.2f}  "
              f"BHV={first_vedl['Buy_Hold_Value']:.4f}")
        print(f"  Last pre-demerger row  {last_vedl['Date'].date()}  "
              f"Close={last_vedl['Close']:.2f}  BHV={last_vedl['Buy_Hold_Value']:.4f}")

    # ----------------------------------------------------------------
    # STEP 5: Fetch post-demerger prices for all 5 entities
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 5: Fetching post-demerger prices")
    print("="*65)

    demerger_tickers = list(DEMERGER_RATIOS.keys())   # VEDL, VAML, VISL, VEDPOWER, VOGL
    post_prices, post_errors = fetch_truedata_history(
        ticker_list=demerger_tickers,
        duration='1 Y',
        bar_size='EOD',
        sleep_time=0.2
    )
    if post_errors:
        logging.warning(f"Failed to fetch post-demerger prices for: {post_errors}")

    print(f"Post-demerger price rows: {len(post_prices)}")
    print(post_prices.groupby('Ticker')[['Date']].agg(['min', 'max']))

    # ----------------------------------------------------------------
    # STEP 6: Build demerger segment rows
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 6: Building VEDL demerger segment")
    print("  Demerger date:", VEDL_DEMERGER_DATE.date())
    print("  Adjustment factor (100/52.34):", round(VEDL_ADJ_FACTOR, 6))
    print("="*65)

    demerger_seg = build_vedl_demerger_segment(conc_df, post_prices)

    if demerger_seg.empty:
        print("\nWARNING: No demerger segment built — saving conc_df as-is.")
        conc_df_final = conc_df
    else:
        # -----------------------------------------------------------
        # STEP 7: Remove VEDL rows after demerger date from conc_df
        #         and append the 5 demerger entity rows
        # -----------------------------------------------------------
        print(f"\nDemerger segment shape: {demerger_seg.shape}")
        print(f"Demerger entities: {demerger_seg['Ticker'].unique().tolist()}")

        conc_df_trimmed = conc_df[
            ~((conc_df['Ticker'] == 'VEDL') &
              (pd.to_datetime(conc_df['Date']) > VEDL_DEMERGER_DATE))
        ].copy()

        conc_df_final = pd.concat([conc_df_trimmed, demerger_seg], ignore_index=True) \
                          .sort_values(['Date', 'Ticker']).reset_index(drop=True)

        # -----------------------------------------------------------
        # STEP 8: Recompute Total_Portfolio_Value per date
        #         (ensures demerger entity values are included in the total)
        # -----------------------------------------------------------
        daily_total = conc_df_final.groupby('Date')['Buy_Hold_Value'].sum().rename('_tpv')
        conc_df_final = conc_df_final.merge(daily_total, on='Date', how='left')
        conc_df_final['Total_Portfolio_Value'] = conc_df_final['_tpv']
        conc_df_final.drop(columns=['_tpv'], inplace=True)

        print(f"\nconc_df_final shape (after demerger): {conc_df_final.shape}")
        print(f"Unique tickers in final output: {sorted(conc_df_final['Ticker'].unique())}")

    # ----------------------------------------------------------------
    # STEP 8.5: Retrospectively fix VEDL's historical Buy_Price
    #           (Set it to the unconsolidated Open of its entry date)
    # ----------------------------------------------------------------
    mask_vedl_all = conc_df_final['Ticker'] == 'VEDL'
    if mask_vedl_all.any():
        vedl_history = conc_df_final[mask_vedl_all].sort_values('Date')
        vedl_first_date = vedl_history['Date'].min()
        vedl_first_row = vedl_history.iloc[0]
        # The Open stored in conc_df_final for dates <= VEDL_DEMERGER_DATE is consolidated
        vedl_first_open_cons = float(vedl_first_row['Open'])
        vedl_true_open = vedl_first_open_cons / VEDL_ADJ_FACTOR if vedl_first_date <= VEDL_DEMERGER_DATE else vedl_first_open_cons
        
        # Update Buy_Price for all VEDL rows
        conc_df_final.loc[mask_vedl_all, 'Buy_Price'] = vedl_true_open

    # ----------------------------------------------------------------
    # STEP 9: Save demerger-adjusted output
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 9: Saving output")
    print("="*65)

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    conc_df_final.to_excel(VEDL_OUTPUT, index=False)
    print(f"\nSaved VEDL demerger-adjusted output:\n  {VEDL_OUTPUT}")
    print(f"Rows: {len(conc_df_final)}  |  Columns: {len(conc_df_final.columns)}")

    # ----------------------------------------------------------------
    # STEP 10: Summary stats
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 10: Portfolio summary")
    print("="*65)

    # Latest date totals
    latest_date = conc_df_final['Date'].max()
    latest_rows = conc_df_final[conc_df_final['Date'] == latest_date][['Ticker', 'Buy_Hold_Value']].copy()
    latest_rows = latest_rows.sort_values('Buy_Hold_Value', ascending=False)
    print(f"\nPortfolio snapshot on {latest_date.date()}")
    print(f"{'Ticker':<12} {'Buy_Hold_Value':>15}")
    print("-" * 30)
    for _, row in latest_rows.iterrows():
        flag = " << DEMERGER" if row['Ticker'] in ('VAML', 'VISL', 'VEDPOWER', 'VOGL') else ""
        print(f"{row['Ticker']:<12} {row['Buy_Hold_Value']:>15.4f}{flag}")
    total_val = latest_rows['Buy_Hold_Value'].sum()
    print("-" * 30)
    print(f"{'TOTAL':<12} {total_val:>15.4f}")

    # VEDL demerger breakdown (just the 5 entities)
    demerger_snapshot = conc_df_final[
        (conc_df_final['Date'] == latest_date) &
        (conc_df_final['Ticker'].isin(DEMERGER_RATIOS.keys()))
    ][['Ticker', 'Initial_Allocation', 'Buy_Hold_Value']].copy()

    if not demerger_snapshot.empty:
        demerger_snapshot['Return_%'] = (
            (demerger_snapshot['Buy_Hold_Value'] / demerger_snapshot['Initial_Allocation']) - 1
        ) * 100
        print(f"\nVEDL Demerger Entity Breakdown on {latest_date.date()}")
        print(demerger_snapshot.to_string(index=False))

    # ----------------------------------------------------------------
    # STEP 11: Benchmark — NIFTY 500
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 11: Fetching NIFTY 500 benchmark")
    print("="*65)

    nse_raw, _ = fetch_truedata_history(
        ticker_list=['NIFTY 500'], duration='5 Y', bar_size='EOD', sleep_time=0.1
    )
    nse = nse_raw[["Date", "Close"]].rename(columns={'Close': 'Buy_Hold_Value'}).copy()
    nse['%change'] = nse['Buy_Hold_Value'].pct_change()
    nse = nse[nse['Date'] >= '2023-04-01'].copy().reset_index(drop=True)

    # Benchmark Change: starts at 100 on Apr 3, 2023 (first row).
    # Each subsequent day: value = previous_value * (1 + %change)
    benchmark = [None] * len(nse)
    if len(nse) > 0:
        pct0 = nse.at[0, '%change']
        benchmark[0] = 100.0 * (1 + pct0) if pd.notna(pct0) else 100.0
        for i in range(1, len(nse)):
            pct = nse.at[i, '%change']
            benchmark[i] = benchmark[i - 1] * (1 + pct) if pd.notna(pct) else benchmark[i - 1]
    nse['Benchmark Change'] = benchmark

    nse_out = os.path.join(OUTPUT_FOLDER, "nse500_Nifty_500_2025_Apr_nse500_nse500_nse500_nse500_nse500_returns.xlsx")
    nse.to_excel(nse_out, index=False)
    print(f"Saved NIFTY 500 benchmark: {nse_out}")
    print(f"Rows: {len(nse)} | Benchmark Change: start=100.0, end={benchmark[-1]:.4f}")

    print("\n" + "="*65)
    print("  ALL DONE")
    print("="*65 + "\n")

    return conc_df_final


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == '__main__':
    result_df = main()
