"""
july_2026_daily_equity_only.py
==============================
Derived from: july_2026_daily.py

EQUITY-ONLY BUY & HOLD  (NO HEDGE LEG)
--------------------------------------
This is the same momentum buy&hold pipeline as july_2026_daily.py, but with the
entire hedge book removed:

  REMOVED:
    - GOLDBEES gold leg in the base portfolio
    - The rebalanced hedge book (GOLDBEES / SILVERBEES / MOGSEC / LIQUIDCASE /
      CPSEETF / PHARMABEES / NEXT50IETF / DEFENCE)
    - The July 2026 GOLDBEES -> DEFENCE hedge transfer

  KEPT:
    - Momentum equity portfolio with month-by-month rebalancing
    - VEDL demerger handling (VEDL is an equity holding, not a hedge)
    - July 2026 equity rebalance correction (Vedanta group = 1 combined slot)
    - NIFTY 500 benchmark + Portfolio-vs-Benchmark summary

Total_Portfolio_Value in the output is therefore the sum of equity
Buy_Hold_Value only.

ALLOCATION NOTE
---------------
july_2026_daily.py splits 100 into 75 equity + 25 hedge. With the hedge removed
there is nothing to hold the other 25, so EQUITY_ALLOCATION below defaults to
100 (a fully-invested equity portfolio starting at 100 on the inception date).
Set it to 75 if you instead want the equity leg to match the hedged script's
equity numbers exactly. Everything scales linearly with this number.

JULY 2026 REBALANCE LOGIC (equity, unchanged)
---------------------------------------------
On 2026-07-01:
  - All 5 Vedanta entities (VEDL, VAML, VISL, VEDPOWER, VOGL) are sold as ONE
    combined slot - they all originated from a single VEDL position, so they
    count as 1 freed slot (not 5).
  - 8 other stocks also exit: ADANIENSOL, ADANIGREEN, CUMMINSIND, HINDALCO,
    MCX, NATIONALUM, NAVINFLUOR, SAIL
  - Total released = 9 slots (1 Vedanta group + 8 individual stocks)
  - Combined Buy_Hold_Value of all 9 slots on June 30, 2026 is pooled and
    divided by 9 -> new Buy_Hold per incoming stock
  - 9 new stocks enter: ATHERENERG, BANDHANBNK, CPPLUS, FINCABLES, J&KBANK,
    JINDALSAW, RRKABEL, SYRMA, WELCORP

  NOTE: ABSLAMC has been kept in place of HFCL in the July 2026 portfolio.

VEDL DEMERGER (inherited)
-------------------------
  TrueData retroactively adjusted VEDL prices to reflect the demerger
  (fetched prices = 52.34% of original consolidated price).
  1. Restores VEDL to its consolidated price for dates up to 2026-06-14.
  2. On 2026-06-15, splits VEDL BHV into 5 entities via court-approved ratios.
  3. All 5 Vedanta entities are sold at end of June 2026 (July rebalance).
"""

# ============================================================
# 0.  IMPORTS
# ============================================================
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import time
import logging
import sys, os

sys.path.insert(0, r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2")
from truedata_connector import get_td_obj

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ============================================================
# 1.  ALLOCATION
# ============================================================
# Full 100 into equity since there is no hedge leg to carry the other 25.
# Set to 75 to reproduce the equity leg of july_2026_daily.py exactly.
EQUITY_ALLOCATION = 100

# ============================================================
# 2.  VEDL DEMERGER CONSTANTS
# ============================================================
VEDL_DEMERGER_DATE    = pd.Timestamp('2026-06-14')   # last consolidated trading day was before 15th
VEDL_ADJ_FACTOR       = 100.0 / 52.34               # ~1.9106  (restores consolidated price)

# Ratios per the NCLT/court-approved demerger scheme
DEMERGER_RATIOS = {
    'VEDL':     0.5234,   # Vedanta Limited (residual)
    'VAML':     0.0715,   # Vedanta Aluminium Metal Ltd
    'VISL':     0.0679,   # Vedanta Iron and Steel Ltd
    'VEDPOWER': 0.1223,   # Talwandi Sabo Power Ltd
    'VOGL':     0.2149,   # Malco Energy Ltd
}

# ============================================================
# 3.  JULY 2026 REBALANCE CONSTANTS
# ============================================================
JULY_REBALANCE_DATE = pd.Timestamp('2026-07-01')

# All 5 Vedanta entities are counted as ONE slot for rebalance purposes
# (they all originated from a single VEDL position before the demerger).
VEDANTA_GROUP_TICKERS = ['VEDL', 'VAML', 'VISL', 'VEDPOWER', 'VOGL']

# Other 8 stocks that left the portfolio after June 2026
OTHER_DROPPED_JULY = [
    'ADANIENSOL', 'ADANIGREEN', 'CUMMINSIND', 'HINDALCO',
    'MCX', 'NATIONALUM', 'NAVINFLUOR', 'SAIL',
]

# 9 new stocks entering on July 1, 2026
# NOTE: ABSLAMC has been kept in place of HFCL in the July 2026 portfolio.
JULY_NEW_STOCKS = [
    'ATHERENERG', 'BANDHANBNK', 'CPPLUS', 'FINCABLES',
    'J&KBANK', 'JINDALSAW', 'RRKABEL', 'SYRMA', 'WELCORP',
]

# Total freed slots = 1 (Vedanta group) + 8 (individual) = 9
JULY_NEW_SLOTS = 9

# Reference new-stock allocation at the hedged script's 75 equity allocation.
# Scales linearly with EQUITY_ALLOCATION.
JULY_NEW_ALLOC_REFERENCE_AT_75 = 10.521

# ============================================================
# 4.  TRUEDATA FETCH HELPER
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
# 5.  PORTFOLIO PROCESSING
# ============================================================
def process_portfolio(nav_df, ticker_data, initial_value=100, inception_date=None, output_file=None):
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


def build_weighted_segment(prices, start_date, end_date, base_values, segment_name,
                           new_tickers=None):
    """
    Generic compounding segment builder. Used here only for the VEDL demerger
    entities (the hedge segments it originally served have been removed).

    new_tickers: list of tickers entering this segment fresh (bought at Open on Day 1).
                 All others are assumed to be continuing (overnight close-to-close on Day 1).
    """
    if new_tickers is None:
        new_tickers = []

    segment = prices[
        (prices['Date'] >= start_date)
        & (prices['Date'] <= end_date)
        & (prices['Ticker'].isin(base_values))
    ][['Date', 'Ticker', 'Open', 'Close']].copy()
    if segment.empty:
        return segment

    segment = segment.sort_values(['Ticker', 'Date'])

    full_history = prices[
        prices['Ticker'].isin(base_values)
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

    buy_prices            = segment.groupby('Ticker')['Close'].transform('first')
    segment['Buy_Price']  = buy_prices
    segment['Quantity']   = np.where(buy_prices > 0, segment['Initial_Allocation'] / buy_prices, 0.0)
    segment['Selection_Date']        = start_date
    segment['Segment']               = segment_name
    segment['Total_Portfolio_Value'] = segment.groupby('Date')['Buy_Hold_Value'].transform('sum')
    return segment.drop(columns=['ret_factor', 'cum_factor'])


# ============================================================
# 6.  PREPARE & PROCESS  (equity only, with VEDL consolidation hook)
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


def prepare_and_process_equity(input_file, start_date, end_date,
                               process_portfolio_fn,
                               equity_allocation=EQUITY_ALLOCATION,
                               apply_vedl_adj=False):
    """
    Prepare the momentum equity dataframe and process its buy&hold performance.
    No GOLDBEES / gold leg and no hedge instruments are added.

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
    nav_df = nav_df.sort_values(['Date', 'Ticker']).reset_index(drop=True)

    # --- Equity leg (the only leg) ---
    symbol_list = nav_df['Ticker'].dropna().unique()
    ticker_data, errors = fetch_truedata_history(
        ticker_list=symbol_list, duration='10 Y', bar_size='EOD', sleep_time=0.1
    )
    if errors:
        logging.warning(f'Failed to fetch data for {errors}')

    # Apply VEDL consolidation BEFORE compounding
    if apply_vedl_adj:
        ticker_data = apply_vedl_consolidation(ticker_data)

    inception_date = pd.to_datetime(start_date)

    final_df = process_portfolio_fn(
        nav_df, ticker_data, equity_allocation, inception_date=inception_date
    )

    return final_df.sort_values(['Date', 'Ticker']).reset_index(drop=True)


# ============================================================
# 7.  VEDL DEMERGER SEGMENT BUILDER
# ============================================================
def build_vedl_demerger_segment(equity_df: pd.DataFrame,
                                post_prices: pd.DataFrame) -> pd.DataFrame:
    """
    Reads VEDL's last consolidated Buy_Hold_Value (on or before VEDL_DEMERGER_DATE)
    from the already-processed equity_df, seeds 5 entities using DEMERGER_RATIOS,
    and builds a Buy_Hold segment for the post-demerger period.

    All 5 entities are treated as NEW (bought at Open on first trading day after
    VEDL_DEMERGER_DATE) so there is no artificial price-gap return on day 1.
    """
    # ------------------------------------------------------------------
    # Step 1: Find VEDL's last consolidated BHV
    # ------------------------------------------------------------------
    vedl_rows = equity_df[
        (equity_df['Ticker'] == 'VEDL') &
        (pd.to_datetime(equity_df['Date']) <= VEDL_DEMERGER_DATE)
    ].sort_values('Date')

    if vedl_rows.empty:
        logging.error("No VEDL rows found on or before demerger date - skipping demerger segment.")
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
        logging.info(f"  {t:<10} {DEMERGER_RATIOS[t]*100:.2f}%  ->  {v:.4f}")

    # ------------------------------------------------------------------
    # Step 3: Find first trading day after demerger date
    # ------------------------------------------------------------------
    post_prices = post_prices.copy()
    post_prices['Date'] = pd.to_datetime(post_prices['Date'])

    available_tickers = post_prices['Ticker'].unique().tolist()
    missing = [t for t in DEMERGER_RATIOS if t not in available_tickers]
    if missing:
        logging.warning(f"[Demerger] Missing tickers in post_prices: {missing} - they will be absent from output.")
        base_values = {k: v for k, v in base_values.items() if k in available_tickers}

    post_filtered = post_prices[post_prices['Date'] > VEDL_DEMERGER_DATE]
    if post_filtered.empty:
        logging.warning("[Demerger] No post-demerger price data available after demerger date.")
        return pd.DataFrame()

    post_start = post_filtered['Date'].min()
    # Cap demerger segment at June 30, 2026 - all 5 Vedanta entities are
    # sold as one combined slot at the July 2026 monthly rebalance.
    post_end   = min(post_filtered['Date'].max(), pd.Timestamp('2026-06-30'))

    logging.info(f"[Demerger] Post-demerger segment: {post_start.date()} -> {post_end.date()} "
                 f"(capped at Jun 30 - sold at July 2026 rebalance)")

    # ------------------------------------------------------------------
    # Step 4: Build the segment (all 5 are 'new' -> Day-1 uses intraday return)
    # ------------------------------------------------------------------
    segment = build_weighted_segment(
        prices=post_prices,
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
            segment.loc[mask, 'Quantity'] = np.where(
                first_open > 0, segment.loc[mask, 'Initial_Allocation'] / first_open, 0.0
            )

    # 2. For VEDL: Buy_Price = Unconsolidated Open price on its entry date into the portfolio
    vedl_entry_date = vedl_rows['Date'].min()
    vedl_entry_open_cons = float(vedl_rows[vedl_rows['Date'] == vedl_entry_date]['Open'].iloc[0])
    vedl_true_open = vedl_entry_open_cons / VEDL_ADJ_FACTOR

    mask_vedl = segment['Ticker'] == 'VEDL'
    if mask_vedl.any():
        segment.loc[mask_vedl, 'Buy_Price'] = vedl_true_open
        segment.loc[mask_vedl, 'Quantity'] = np.where(
            vedl_true_open > 0, segment.loc[mask_vedl, 'Initial_Allocation'] / vedl_true_open, 0.0
        )

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
# 8.  JULY 2026 EQUITY REBALANCE CORRECTION
# ============================================================
def apply_july_2026_rebalance_correction(equity_df_final: pd.DataFrame,
                                         equity_allocation: float = EQUITY_ALLOCATION) -> pd.DataFrame:
    """
    Corrects July 2026 new-stock allocations.

    process_portfolio() computes the July new-stock allocation using only
    VEDL's BHV from its own tracking (it never saw VAML/VISL/VEDPOWER/VOGL
    which were added separately via the demerger segment).

    This function:
      1. Removes all Vedanta-entity rows dated >= 2026-07-01 (they are sold).
      2. Reads the June 30 Buy_Hold_Values for all 9 freed slots:
           - Vedanta group combined: VEDL+VAML+VISL+VEDPOWER+VOGL (= 1 slot)
           - 8 individual dropped stocks
      3. Computes correct_new_alloc = total_freed_BHV / 9
      4. Scales Buy_Hold_Value, Initial_Allocation and Quantity for the 9
         new July stocks to match correct_new_alloc.
      5. Recomputes Total_Portfolio_Value for all dates.
    """
    df = equity_df_final.copy()
    df['Date'] = pd.to_datetime(df['Date'])

    # ------------------------------------------------------------------
    # Step 1: Drop Vedanta entity rows from July 1 onwards
    # ------------------------------------------------------------------
    vedanta_july_mask = (
        df['Ticker'].isin(VEDANTA_GROUP_TICKERS) &
        (df['Date'] >= JULY_REBALANCE_DATE)
    )
    n_removed = vedanta_july_mask.sum()
    df = df[~vedanta_july_mask].copy()
    logging.info(f"[July Rebalance] Removed {n_removed} Vedanta-entity rows "
                 f"dated >= {JULY_REBALANCE_DATE.date()}")

    # ------------------------------------------------------------------
    # Step 2: Get June 30 (last trading day of June) snapshot
    # ------------------------------------------------------------------
    june_rows = df[df['Date'].dt.to_period('M').astype(str) == '2026-06']
    if june_rows.empty:
        logging.warning("[July Rebalance] No June 2026 rows found - skipping correction.")
        return df

    june_last_date = june_rows['Date'].max()
    june_snap = (
        df[df['Date'] == june_last_date]
        .set_index('Ticker')['Buy_Hold_Value']
    )

    # ------------------------------------------------------------------
    # Step 3: Compute the correct new allocation
    # ------------------------------------------------------------------
    vedanta_combined_bhv = sum(june_snap.get(t, 0.0) for t in VEDANTA_GROUP_TICKERS)
    other_dropped_bhv    = sum(june_snap.get(t, 0.0) for t in OTHER_DROPPED_JULY)
    total_freed_bhv      = vedanta_combined_bhv + other_dropped_bhv
    correct_new_alloc    = total_freed_bhv / JULY_NEW_SLOTS

    expected_alloc = JULY_NEW_ALLOC_REFERENCE_AT_75 * equity_allocation / 75.0

    print(f"\n{'='*65}")
    print("  JULY 2026 EQUITY REBALANCE SUMMARY  (equity only, no hedge)")
    print(f"{'='*65}")
    print(f"  Last June trading day             : {june_last_date.date()}")
    print(f"  Vedanta group BHV (counts as 1 slot):")
    for t in VEDANTA_GROUP_TICKERS:
        print(f"    {t:<10}: {june_snap.get(t, 0.0):.4f}")
    print(f"  Vedanta combined                  : {vedanta_combined_bhv:.4f}")
    print(f"  Other 8 dropped stocks BHV:")
    for t in OTHER_DROPPED_JULY:
        print(f"    {t:<12}: {june_snap.get(t, 0.0):.4f}")
    print(f"  Other dropped total               : {other_dropped_bhv:.4f}")
    print(f"  Total freed BHV (9 slots)         : {total_freed_bhv:.4f}")
    print(f"  New Buy_Hold per stock (/9)       : {correct_new_alloc:.4f}  "
          f"[scaled reference: {expected_alloc:.4f}]")
    print(f"  9 new stocks entering July        : {JULY_NEW_STOCKS}")
    print(f"  NOTE: ABSLAMC has been kept in place of HFCL in the July 2026 portfolio.")

    # ------------------------------------------------------------------
    # Step 4: Find the allocation process_portfolio used for July new stocks
    # ------------------------------------------------------------------
    july_new_mask = (
        df['Ticker'].isin(JULY_NEW_STOCKS) &
        (df['Date'] >= JULY_REBALANCE_DATE)
    )

    if not july_new_mask.any():
        logging.warning("[July Rebalance] No July new stock rows found - "
                        "skipping Buy_Hold correction.")
        return df

    process_alloc = float(df.loc[july_new_mask, 'Initial_Allocation'].iloc[0])
    if process_alloc <= 0:
        logging.warning(f"[July Rebalance] process_alloc={process_alloc} invalid - skipping.")
        return df

    scale_factor = correct_new_alloc / process_alloc

    print(f"\n  process_portfolio alloc (VEDL-only basis) : {process_alloc:.4f}")
    print(f"  Correction scale factor                   : {scale_factor:.6f}")
    print(f"{'='*65}\n")

    # ------------------------------------------------------------------
    # Step 5: Apply scale to all July new-stock rows
    # ------------------------------------------------------------------
    df.loc[july_new_mask, 'Buy_Hold_Value']    *= scale_factor
    df.loc[july_new_mask, 'Quantity']           *= scale_factor
    df.loc[july_new_mask, 'Initial_Allocation'] = correct_new_alloc

    logging.info(f"[July Rebalance] Scaled {july_new_mask.sum()} rows for "
                 f"{df.loc[july_new_mask, 'Ticker'].nunique()} new July stocks. "
                 f"scale_factor={scale_factor:.6f}")

    # ------------------------------------------------------------------
    # Step 6: Recompute Total_Portfolio_Value for ALL dates
    # ------------------------------------------------------------------
    daily_total = df.groupby('Date')['Buy_Hold_Value'].sum().rename('_tpv')
    df = df.merge(daily_total, on='Date', how='left')
    df['Total_Portfolio_Value'] = df['_tpv']
    df.drop(columns=['_tpv'], inplace=True)

    return df


# ============================================================
# 9.  MAIN EXECUTION
# ============================================================
def main():
    # ----------------------------------------------------------------
    # CONFIG - adjust paths here if needed
    # ----------------------------------------------------------------
    INPUT_FILE    = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results\master_momentum_summary.xlsx"
    START_DATE    = "2023-04-01"
    END_DATE      = date.today().strftime('%Y-%m-%d')
    # Equity-only results go to their own folder so nothing from the hedged
    # run in ...\Trials is touched. Created automatically if missing.
    OUTPUT_FOLDER = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials_EquityOnly"

    EQUITY_OUTPUT = os.path.join(
        OUTPUT_FOLDER,
        "Nifty_500_2025_Apr_20_stocks_results_EquityOnly_buy&hold_returns.xlsx"
    )
    BENCHMARK_OUTPUT = os.path.join(OUTPUT_FOLDER, "nse500_benchmark_EquityOnly_returns.xlsx")
    SUMMARY_OUTPUT   = os.path.join(OUTPUT_FOLDER, "Portfolio_vs_Benchmark_July2026_EquityOnly.xlsx")

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)
    print(f"Output folder: {OUTPUT_FOLDER}")

    # ----------------------------------------------------------------
    # STEP 1: Run the equity-only portfolio pipeline
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 1: Running EQUITY-ONLY portfolio pipeline (no hedge leg)")
    print(f"  Equity allocation: {EQUITY_ALLOCATION}")
    print("  (VEDL prices restored to consolidated values)")
    print("  July 2026: Vedanta group exits as 1 slot")
    print("="*65)

    equity_df = prepare_and_process_equity(
        input_file=INPUT_FILE,
        start_date=START_DATE,
        end_date=END_DATE,
        process_portfolio_fn=process_portfolio,
        equity_allocation=EQUITY_ALLOCATION,
        apply_vedl_adj=True,           # <-- key: restores VEDL consolidated prices
    )

    print(f"\nequity_df shape: {equity_df.shape}")
    print(f"Unique tickers: {equity_df['Ticker'].nunique()}")

    # Verify VEDL consolidated prices look correct
    vedl_sample = equity_df[equity_df['Ticker'] == 'VEDL'].sort_values('Date')
    if not vedl_sample.empty:
        first_vedl = vedl_sample.iloc[0]
        pre_demerger = vedl_sample[vedl_sample['Date'] <= VEDL_DEMERGER_DATE]
        last_vedl = pre_demerger.iloc[-1] if not pre_demerger.empty else vedl_sample.iloc[-1]
        print(f"\nVEDL consolidated check:")
        print(f"  First row  {first_vedl['Date'].date()}  Close={first_vedl['Close']:.2f}  "
              f"BHV={first_vedl['Buy_Hold_Value']:.4f}")
        print(f"  Last pre-demerger row  {last_vedl['Date'].date()}  "
              f"Close={last_vedl['Close']:.2f}  BHV={last_vedl['Buy_Hold_Value']:.4f}")

    # ----------------------------------------------------------------
    # STEP 2: Fetch post-demerger prices for all 5 entities
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 2: Fetching post-demerger prices")
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
    if not post_prices.empty:
        print(post_prices.groupby('Ticker')[['Date']].agg(['min', 'max']))

    # ----------------------------------------------------------------
    # STEP 3: Build demerger segment rows
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 3: Building VEDL demerger segment")
    print("  Demerger date:", VEDL_DEMERGER_DATE.date())
    print("  Adjustment factor (100/52.34):", round(VEDL_ADJ_FACTOR, 6))
    print("  Segment capped at: 2026-06-30 (all 5 entities sold at July rebalance)")
    print("="*65)

    demerger_seg = build_vedl_demerger_segment(equity_df, post_prices)

    if demerger_seg.empty:
        print("\nWARNING: No demerger segment built - keeping equity_df as-is.")
        equity_df_final = equity_df
    else:
        # -----------------------------------------------------------
        # STEP 4: Remove VEDL rows after demerger date and append the
        #         5 demerger entity rows
        # -----------------------------------------------------------
        print(f"\nDemerger segment shape: {demerger_seg.shape}")
        print(f"Demerger entities: {demerger_seg['Ticker'].unique().tolist()}")

        equity_df_trimmed = equity_df[
            ~((equity_df['Ticker'] == 'VEDL') &
              (pd.to_datetime(equity_df['Date']) > VEDL_DEMERGER_DATE))
        ].copy()

        equity_df_final = pd.concat([equity_df_trimmed, demerger_seg], ignore_index=True) \
                            .sort_values(['Date', 'Ticker']).reset_index(drop=True)

        # -----------------------------------------------------------
        # STEP 5: Recompute Total_Portfolio_Value per date
        # -----------------------------------------------------------
        daily_total = equity_df_final.groupby('Date')['Buy_Hold_Value'].sum().rename('_tpv')
        equity_df_final = equity_df_final.merge(daily_total, on='Date', how='left')
        equity_df_final['Total_Portfolio_Value'] = equity_df_final['_tpv']
        equity_df_final.drop(columns=['_tpv'], inplace=True)

        print(f"\nequity_df_final shape (after demerger): {equity_df_final.shape}")

    # ----------------------------------------------------------------
    # STEP 6: Retrospectively fix VEDL's historical Buy_Price
    #         (Set it to the unconsolidated Open of its entry date)
    # ----------------------------------------------------------------
    mask_vedl_all = equity_df_final['Ticker'] == 'VEDL'
    if mask_vedl_all.any():
        vedl_history = equity_df_final[mask_vedl_all].sort_values('Date')
        vedl_first_date = vedl_history['Date'].min()
        vedl_first_row  = vedl_history.iloc[0]
        # The Open stored for dates <= VEDL_DEMERGER_DATE is consolidated
        vedl_first_open_cons = float(vedl_first_row['Open'])
        vedl_true_open = vedl_first_open_cons / VEDL_ADJ_FACTOR \
            if vedl_first_date <= VEDL_DEMERGER_DATE else vedl_first_open_cons

        equity_df_final.loc[mask_vedl_all, 'Buy_Price'] = vedl_true_open

    # ----------------------------------------------------------------
    # STEP 7: Apply July 2026 equity rebalance correction
    # ----------------------------------------------------------------
    equity_df_final = apply_july_2026_rebalance_correction(
        equity_df_final, equity_allocation=EQUITY_ALLOCATION
    )

    print(f"equity_df_final shape (after July rebalance correction): {equity_df_final.shape}")
    print(f"Unique tickers post-correction: {sorted(equity_df_final['Ticker'].unique())}")

    # ----------------------------------------------------------------
    # STEP 8: Save equity-only output
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 8: Saving output")
    print("="*65)

    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    equity_df_final.to_excel(EQUITY_OUTPUT, index=False)
    print(f"\nSaved equity-only buy&hold output:\n  {EQUITY_OUTPUT}")
    print(f"Rows: {len(equity_df_final)}  |  Columns: {len(equity_df_final.columns)}")

    # ----------------------------------------------------------------
    # STEP 9: Summary stats
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 9: Portfolio summary (equity only)")
    print("="*65)

    latest_date = equity_df_final['Date'].max()
    latest_rows = equity_df_final[equity_df_final['Date'] == latest_date][['Ticker', 'Buy_Hold_Value']].copy()
    latest_rows = latest_rows.sort_values('Buy_Hold_Value', ascending=False)
    print(f"\nPortfolio snapshot on {latest_date.date()}")
    print(f"{'Ticker':<14} {'Buy_Hold_Value':>15}")
    print("-" * 32)
    for _, row in latest_rows.iterrows():
        flag = " << NEW JULY" if row['Ticker'] in JULY_NEW_STOCKS else ""
        print(f"{row['Ticker']:<14} {row['Buy_Hold_Value']:>15.4f}{flag}")
    total_val = latest_rows['Buy_Hold_Value'].sum()
    print("-" * 32)
    print(f"{'TOTAL':<14} {total_val:>15.4f}")

    july1_data = equity_df_final[
        (pd.to_datetime(equity_df_final['Date']) == JULY_REBALANCE_DATE) &
        (equity_df_final['Ticker'].isin(JULY_NEW_STOCKS))
    ][['Ticker', 'Initial_Allocation', 'Buy_Hold_Value']].copy()
    if not july1_data.empty:
        print(f"\nJuly 1 allocation check for new stocks:")
        print(july1_data.to_string(index=False))

    # ----------------------------------------------------------------
    # STEP 10: Benchmark - NIFTY 500
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 10: Fetching NIFTY 500 benchmark")
    print("="*65)

    nse_raw, _ = fetch_truedata_history(
        ticker_list=['NIFTY 500'], duration='5 Y', bar_size='EOD', sleep_time=0.1
    )
    nse = nse_raw[["Date", "Close"]].rename(columns={'Close': 'Buy_Hold_Value'}).copy()
    nse['%change'] = nse['Buy_Hold_Value'].pct_change()
    nse = nse[nse['Date'] >= START_DATE].copy().reset_index(drop=True)

    # Benchmark Change: starts at 100 on the first row.
    # Each subsequent day: value = previous_value * (1 + %change)
    benchmark = [None] * len(nse)
    if len(nse) > 0:
        pct0 = nse.at[0, '%change']
        benchmark[0] = 100.0 * (1 + pct0) if pd.notna(pct0) else 100.0
        for i in range(1, len(nse)):
            pct = nse.at[i, '%change']
            benchmark[i] = benchmark[i - 1] * (1 + pct) if pd.notna(pct) else benchmark[i - 1]
    nse['Benchmark Change'] = benchmark

    nse.to_excel(BENCHMARK_OUTPUT, index=False)
    print(f"Saved NIFTY 500 benchmark: {BENCHMARK_OUTPUT}")
    if benchmark:
        print(f"Rows: {len(nse)} | Benchmark Change: start=100.0, end={benchmark[-1]:.4f}")

    # ----------------------------------------------------------------
    # STEP 11: Summary comparison table
    #   Columns: Date | Total_Portfolio_Value | Benchmark Change
    # ----------------------------------------------------------------
    print("\n" + "="*65)
    print("  STEP 11: Building Portfolio vs Benchmark summary table")
    print("="*65)

    port_daily = (
        equity_df_final
        .groupby('Date', as_index=False)['Buy_Hold_Value']
        .sum()
        .rename(columns={'Buy_Hold_Value': 'Total_Portfolio_Value'})
    )
    port_daily['Date'] = pd.to_datetime(port_daily['Date'])

    bench_daily = nse[['Date', 'Benchmark Change']].copy()
    bench_daily['Date'] = pd.to_datetime(bench_daily['Date'])

    summary = pd.merge(port_daily, bench_daily, on='Date', how='outer').sort_values('Date')
    summary = summary[['Date', 'Total_Portfolio_Value', 'Benchmark Change']].reset_index(drop=True)

    summary.to_excel(SUMMARY_OUTPUT, index=False)
    print(f"Saved summary table: {SUMMARY_OUTPUT}")
    print(f"Rows: {len(summary)}")
    print(summary.tail(5).to_string(index=False))

    print("\n" + "="*65)
    print("  ALL DONE  (equity only - no hedge instruments in output)")
    print("="*65 + "\n")

    return equity_df_final


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == '__main__':
    result_df = main()
