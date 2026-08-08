import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import yfinance as yf
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import time
import logging
import pandas as pd
from truedata import TD_hist

def fetch_truedata_history(
    ticker_list: list,
    duration: str = '1 Y',
    bar_size: str = 'EOD',
    sleep_time: float = 0.1
) -> tuple[pd.DataFrame, list]:
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
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    username =  os.getenv("TRUEDATA_USERNAME")
    password = os.getenv("TRUEDATA_PASSWORD")
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


import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

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
                stock_data_flt.loc[ticker_index, 'Real_Rank'] = month_nav.loc[month_nav['Ticker'] == ticker, 'Real_Rank'].iloc[0]

        last_month_quantity = stock_data_flt.groupby('Ticker')['Quantity'].last().to_dict()
        last_month_value = stock_data_flt.groupby('Ticker')['Buy_Hold_Value'].last().to_dict()
        stock_data_flt['Total_Portfolio_Value'] = stock_data_flt.groupby('Date')['Buy_Hold_Value'].transform('sum')
        df_lis.append(stock_data_flt)

    if not df_lis:
        return pd.DataFrame()
        
    final_df = pd.concat(df_lis, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)

    if output_file:
        final_df.to_excel(output_file, index=False)

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
    hedge_seed = float(hedge_start_factor['Buy_Hold_Value'].iloc[-1]) if not hedge_start_factor.empty else default_hedge_value

    from truedata import TD_hist
    import time
    
    def get_hedge_prices(tickers):
        username = os.getenv("TRUEDATA_USERNAME")
        password = os.getenv("TRUEDATA_PASSWORD")
        td_hist = TD_hist(username, password)
        df_list = []
        for ticker in tickers:
            try:
                df = td_hist.get_historic_data([ticker], duration='5 Y', bar_size='EOD')
                if df is None or df.empty: continue
                df['Ticker'] = ticker
                rename_dict = {}
                if 'timestamp' in df.columns: rename_dict['timestamp'] = 'Date'
                elif 'datetime' in df.columns: rename_dict['datetime'] = 'Date'
                elif 'date' in df.columns: rename_dict['date'] = 'Date'
                rename_dict.update({'high': 'High', 'low': 'Low', 'close': 'Close', 'open': 'Open'})
                df = df.rename(columns=rename_dict)
                df_list.append(df)
                time.sleep(0.1)
            except Exception:
                pass
        return pd.concat(df_list, ignore_index=True) if df_list else pd.DataFrame()

    hedge_prices = get_hedge_prices(['GOLDBEES', 'SILVERBEES', 'MOGSEC', 'LIQUIDCASE', 'CPSEETF', 'NEXT50IETF'])

    segments = []

    decjan_start = pd.Timestamp('2025-12-01')
    decjan_end = min(pd.Timestamp('2026-01-31'), portfolio_end_date)
    if portfolio_end_date >= decjan_start:
        decjan_values = {'GOLDBEES': 0.60 * hedge_seed, 'SILVERBEES': 0.20 * hedge_seed, 'MOGSEC': 0.20 * hedge_seed}
        df_decjan = build_weighted_hedge_segment(
            hedge_prices, start_date=decjan_start, end_date=decjan_end,
            base_values=decjan_values, segment_name='2025-12_to_2026-01'
        )
        if not df_decjan.empty: segments.append(df_decjan)
        else: df_decjan = pd.DataFrame()
    else:
        df_decjan = pd.DataFrame()

    feb_start = pd.Timestamp('2026-02-01')
    feb_end = min(pd.Timestamp('2026-02-28'), portfolio_end_date)
    if portfolio_end_date >= feb_start and not df_decjan.empty:
        feb_factor = df_decjan.groupby('Date', as_index=False)['Buy_Hold_Value'].sum().sort_values('Date')['Buy_Hold_Value'].iloc[-1]
        feb_values = {'GOLDBEES': 0.40 * feb_factor, 'MOGSEC': 0.60 * feb_factor}
        df_feb = build_weighted_hedge_segment(
            hedge_prices, start_date=feb_start, end_date=feb_end,
            base_values=feb_values, segment_name='2026-02'
        )
        if not df_feb.empty: segments.append(df_feb)
        else: df_feb = pd.DataFrame()
    else:
        df_feb = pd.DataFrame()

    mar_start = pd.Timestamp('2026-03-01')
    mar_end = min(pd.Timestamp('2026-04-30'), portfolio_end_date)
    df_mar = pd.DataFrame()
    if portfolio_end_date >= mar_start and not df_feb.empty:
        feb_last_date = df_feb['Date'].max()
        feb_last = df_feb[df_feb['Date'] == feb_last_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
        mar_values = {'GOLDBEES': feb_last.get('GOLDBEES', 0.0), 'LIQUIDCASE': feb_last.get('MOGSEC', 0.0)}
        df_mar = build_weighted_hedge_segment(
            hedge_prices, start_date=mar_start, end_date=mar_end,
            base_values=mar_values, segment_name='2026-03_to_2026-04' if portfolio_end_date >= mar_end else '2026-03_onward'
        )
        if not df_mar.empty: segments.append(df_mar)

    may_start = pd.Timestamp('2026-05-01')
    if portfolio_end_date >= may_start and not df_mar.empty:
        mar_last_date = df_mar['Date'].max()
        mar_last = df_mar[df_mar['Date'] == mar_last_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
        total_hedge_value = sum(mar_last.values())
        
        may_values = {
            'GOLDBEES': 0.20 * total_hedge_value,
            'LIQUIDCASE': 0.40 * total_hedge_value,
            'CPSEETF': 0.20 * total_hedge_value,
            'NEXT50IETF': 0.20 * total_hedge_value,
        }
        df_may = build_weighted_hedge_segment(
            hedge_prices, start_date=may_start, end_date=portfolio_end_date,
            base_values=may_values, segment_name='2026-05_onward'
        )
        if not df_may.empty: segments.append(df_may)

    if not segments:
        return pd.DataFrame()

    return pd.concat(segments, ignore_index=True).sort_values(['Date', 'Ticker']).reset_index(drop=True)


import os
import pandas as pd

def prepare_and_process_portfolio(input_file, start_date, end_date, output_folder,
                                  process_portfolio,
                                  equity_allocation=75, gold_allocation=25):
    # Load and clean
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

    # Add GOLDBEES for each unique date
    goldbees_df = pd.DataFrame({
        'Date': nav_df['Date'].drop_duplicates().sort_values(),
        'Ticker': 'GOLDBEES'
    })
    if 'Real_Rank' in nav_df.columns:
        goldbees_df['Real_Rank'] = np.nan
    goldbees_df['Year-Month'] = pd.to_datetime(goldbees_df['Date']).dt.to_period('M').astype(str)

    # Combine
    concat_df = (
        pd.concat([nav_df, goldbees_df], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )

    # Split
    ticker_df = concat_df.query("Ticker != 'GOLDBEES'")
    symbol_list = ticker_df['Ticker'].unique()
    ticker_data_other_stocks = fetch_truedata_history(
        ticker_list = symbol_list,
        duration = '10 Y',
        bar_size = 'EOD',
        sleep_time= 0.1
    )[0]

    gold_df = concat_df.query("Ticker == 'GOLDBEES'")
    symbol_list = gold_df['Ticker'].unique()
    ticker_data_gold = fetch_truedata_history(
        ticker_list = symbol_list,
        duration = '10 Y',
        bar_size = 'EOD',
        sleep_time= 0.1
    )[0]

    # Process
    inception_date = pd.to_datetime(start_date)
    final_df_other_stocks = process_portfolio(ticker_df, ticker_data_other_stocks, equity_allocation, inception_date=inception_date)
    final_df_gold = process_portfolio(gold_df, ticker_data_gold, gold_allocation, inception_date=inception_date)

    # Merge results
    final_df = (
        pd.concat([final_df_other_stocks, final_df_gold], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    middle_folder = os.path.basename(os.path.dirname(input_file))
    output_file = os.path.join(output_folder, f"{middle_folder}_gold_buy&hold_returns.xlsx")
    print(f"Final output saved to: {output_file}")

    return final_df


#NSE500

final_df = prepare_and_process_portfolio(
    input_file=r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results\master_momentum_summary.xlsx",
    start_date="2025-11-11",
    end_date=pd.Timestamp.today().normalize().strftime('%Y-%m-%d') ,
    output_folder="Trials",
    process_portfolio=process_portfolio
)

import plotly.express as px

# ✅ Group by Date and calculate total portfolio value
portfolio_summary = (
    final_df.groupby("Date", as_index=False)["Buy_Hold_Value"].sum()
)

# ✅ Plot with Plotly
fig = px.line(
    portfolio_summary,
    x="Date",
    y="Buy_Hold_Value",
    title="Buy_Hold_Value Over Time",
    labels={"Date": "Date", "Buy_Hold_Value": "Buy_Hold_Value"},
    markers=True
)

fig.update_traces(line=dict(width=2))
fig.update_layout(width=1000,   # 🔑 width
                  height=500)    # 🔑 height



final_df

final_df

old_df = final_df[~((final_df['Date']>'2025-11-30') & (final_df['Ticker']=='GOLDBEES'))]
old_df

old_df['Ticker'].unique()

# Build hedge book using the rebalancing function
portfolio_end_date = pd.to_datetime(final_df['Date']).max()
df = build_rebalanced_hedge_book(
    base_portfolio_df=final_df,
    portfolio_end_date=portfolio_end_date,
    default_hedge_value=25.0
)
df



# Hedge rebalancing is computed in the previous cell; quick sanity view:
df[['Date', 'Ticker', 'Buy_Hold_Value']].head()

# (No-op) Hedge valuation already computed above.
df.tail()

# df



conc_df = pd.concat([old_df, df])
conc_df



import plotly.express as px

# ✅ Group by Date and calculate total portfolio value
portfolio_summary = (
    conc_df.groupby("Date", as_index=False)["Buy_Hold_Value"].sum()
)
# ✅ Plot with Plotly
fig = px.line(
    portfolio_summary,
    x="Date",
    y="Buy_Hold_Value",
    title="Buy_Hold_Value Over Time",
    labels={"Date": "Date", "Buy_Hold_Value": "Buy_Hold_Value"},
    markers=True
)

fig.update_traces(line=dict(width=2))
fig.update_layout(width=1000,   # 🔑 width
                  height=500)    # 🔑 height


# Momentum/Automating Momentum True Data/Trials/Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx

 # conc_df.to_excel('C://Users//Admin//Momentum//Automating Momentum True Data//Trials//Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx', index=False)

conc_df

conc_df['Asset Type'] = np.where(
    conc_df['Ticker'] == 'GOLDBEES', 'Gold',
    np.where(
        conc_df['Ticker'] == 'SILVERBEES', 'Silver',
        np.where(
            conc_df['Ticker'] == 'MOGSEC', 'Debt',
            'Equities'
        )
    )
)

conc_df

# conc_df = conc_df[conc_df['Date']<='2026-01-06']
conc_df = conc_df[conc_df['Date'] <= pd.Timestamp.today().normalize()]
conc_df

conc_df.to_excel('Momentum_Maxfolio_NEW.xlsx', index=False)