# %%
import numpy as np
import pandas as pd
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import pytz
import yfinance as yf
import pyodbc
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')
import time
import logging
import pandas as pd
from truedata import TD_hist
import requests

# %%
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
    username = 'tdwsf695'
    password = 'ocean@695'
    # Initialize connection
    td_hist = TD_hist(username, password)
    df_list = []
    error_list = []
    for ticker in ticker_list:
        try:
            df = td_hist.get_historic_data([ticker], duration=duration, bar_size=bar_size)

            df['Ticker'] = ticker
            # Check column names and rename accordingly
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

# %%
import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

def process_portfolio(nav_df, ticker_data, initial_value=75, output_file=None):
    """
    Process portfolio allocation and returns final dataframe with portfolio performance.

    Parameters
    ----------
    nav_df : pd.DataFrame
        Dataframe with at least ['Year-Month', 'Ticker'] columns.
    get_individual_stock_data : function
        Function to fetch OHLC data. Must accept (tickers, start_date, end_date) and return DataFrame with ['Date','Ticker','Close'].
    initial_value : float
        Initial portfolio allocation value (default=75).
    debt_ticker : str
        Ticker used as debt/alternative asset (default 'MOGSEC.NS').
    output_file : str or None
        If provided, saves the final dataframe to Excel.

    Returns
    -------
    pd.DataFrame
        Final dataframe with portfolio values.
    """
    df_lis = []
    last_month_value = {}
    year_months = nav_df['Year-Month'].unique()
    for i, year_month in enumerate(year_months):
        print(f"\nProcessing: {year_month}")
        print("Last Month Value:", last_month_value)

        tickers = nav_df[nav_df['Year-Month'] == year_month]['Ticker'].unique()
        year_month_date = pd.to_datetime(f"{year_month}-01")


        prev_month_start = (year_month_date - relativedelta(months=2)).strftime('%Y-%m-%d')
        curr_month_start = year_month_date.strftime('%Y-%m-%d')
        curr_month_end = (year_month_date + pd.offsets.MonthEnd(0)).strftime('%Y-%m-%d')

        # --- Fetch stock data ---
        # stock_data = get_individual_stock_data(tickers, prev_month_start, curr_month_end)
        stock_data = (
            ticker_data[(ticker_data['Date'] >= prev_month_start)
            & (ticker_data['Date'] <= curr_month_end) 
            & (ticker_data['Ticker'].isin(tickers))])
        
        # % change
        stock_data['%change'] = stock_data.groupby('Ticker')['Close'].pct_change()
        # Filter current month
        stock_data_flt = stock_data[
            (stock_data['Date'] >= curr_month_start) & (stock_data['Date'] <= curr_month_end)
        ].copy()

        print(stock_data_flt)

        # --- Portfolio allocation logic ---
        if len(last_month_value) == 0:
            # First month â†’ allocate initial portfolio equally
            allocation_per_stock = initial_value / len(tickers)
            stock_allocations = {t: allocation_per_stock for t in tickers}
        else:
            # Continue portfolio
            stock_allocations = {t: last_month_value[t] for t in tickers if t in last_month_value}

            # Pool value of dropped stocks
            dropped_stocks = [t for t in last_month_value if t not in tickers]
            dropped_value = sum(last_month_value[t] for t in dropped_stocks)

            # New stocks â†’ share the dropped value equally
            new_stocks = [t for t in tickers if t not in last_month_value]
            if new_stocks:
                allocation_per_stock = dropped_value / len(new_stocks)
                for t in new_stocks:
                    stock_allocations[t] = allocation_per_stock

        # Apply allocations into dataframe
        for tkr, init_value in stock_allocations.items():
            tkr_idx = stock_data_flt[stock_data_flt['Ticker'] == tkr].index
            stock_data_flt.loc[tkr_idx, 'Buy_Hold_Value'] = init_value * (
                (1 + stock_data_flt.loc[tkr_idx, '%change'].fillna(0)).cumprod()
            )

        # --- Update last month values ---
        last_month_value = (
            stock_data_flt.groupby('Ticker')['Buy_Hold_Value'].last().to_dict()
        )

        # --- Track total portfolio value ---
        stock_data_flt['Total_Portfolio_Value'] = (
            stock_data_flt.groupby('Date')['Buy_Hold_Value'].transform('sum')
        )

        df_lis.append(stock_data_flt)

    
    final_df = pd.concat(df_lis).reset_index(drop=True)

    if output_file:
        final_df.to_excel(output_file, index=False)

    return final_df

# %%
import os
import pandas as pd

def prepare_and_process_portfolio(input_file, start_date, end_date, output_folder,
                                  process_portfolio,
                                  equity_allocation=75, gold_allocation=25):
    """
    Prepare portfolio dataframe with momentum stocks + GOLDBEES and process performance.

    Parameters
    ----------
    input_file : str
        Path to momentum Excel file (with End_Date, Ticker columns).
    start_date : str (YYYY-MM-DD)
        Start date for filtering.
    end_date : str (YYYY-MM-DD)
        End date for filtering.
    output_folder : str
        Folder to save output file.
    get_individual_stock_data : function
        Function to fetch stock NAV/price data.
    process_pocrtfolio : function
        Function to process equity portion of portfolio.
    process_gold : function
        Function to process gold portion of portfolio.
    equity_allocation : int, optional
        Initial allocation to equities (default=75000).
    gold_allocation : int, optional
        Initial allocation to gold (default=25000).

    Returns
    -------
    final_df : pd.DataFrame
        Combined portfolio dataframe.
    """

    # Load and clean
    nav_df = pd.read_excel(input_file).rename(columns={'End_Date': 'Date'})
    nav_df['Date'] = pd.to_datetime(nav_df['Date'])
    nav_df = (
        nav_df[(nav_df['Date'] >= start_date) & (nav_df['Date'] <= end_date)]
        .reset_index(drop=True)[['Date', 'Ticker']]
    )
    nav_df['Year-Month'] = nav_df['Date'].dt.to_period('M').astype(str)
    stocks = pd.read_excel(input_file)

    # Add GOLDBEES for each unique date
    goldbees_df = pd.DataFrame({
        'Date': nav_df['Date'].unique(),
        'Ticker': 'GOLDBEES'
    })
    goldbees_df['Year-Month'] = pd.to_datetime(goldbees_df['Date']).dt.to_period('M').astype(str)
    # print(goldbees_df)

    # Combine
    concat_df = (
        pd.concat([nav_df, goldbees_df], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )

    # symbol_list = stocks['Ticker'].unique()
    # ticker_data = fetch_truedata_history(
    #     ticker_list = symbol_list,
    #     duration = '5 Y',
    #     bar_size = 'EOD',
    #     sleep_time= 0.1
    # )[0]
    # final_df = process_portfolio(concat_df, ticker_data, equity_allocation)

    
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
    # print(gold_df)

    # Process
    final_df_other_stocks = process_portfolio(ticker_df, ticker_data_other_stocks, equity_allocation)
    # final_df_gold = process_gold(gold_df, get_individual_stock_data, gold_allocation)
    final_df_gold = process_portfolio(gold_df, ticker_data_gold, gold_allocation)


    # Merge results
    final_df = (
        pd.concat([final_df_other_stocks, final_df_gold], ignore_index=True)
          .sort_values(['Date', 'Ticker'])
          .reset_index(drop=True)
    )


    # --- ensure output folder exists ---
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    # --- extract middle folder name from input path ---
    middle_folder = os.path.basename(os.path.dirname(input_file))
    # e.g. for path ".../nifty500_21April2025_results/master_momentum_summary.xlsx"
    # middle_folder = "nifty500_21April2025_results"

    # --- create output filename using middle folder ---
    output_file = os.path.join(output_folder, f"{middle_folder}_gold_buy&hold_returns.xlsx")

    # --- save output ---
    # final_df.to_excel(output_file, index=False)
    print(f"âœ… Final output saved to: {output_file}")

    return final_df

# %%
#NSE500

# %%
final_df = prepare_and_process_portfolio(
    input_file="Stocks/Nifty_500_2025_Apr_20_stocks_results/master_momentum_summary.xlsx",
    start_date="2023-04-01",
    end_date=date.today().strftime('%Y-%m-%d'),
    output_folder="Trials",
    process_portfolio=process_portfolio
)

import plotly.express as px

# âœ… Group by Date and calculate total portfolio value
portfolio_summary = (
    final_df.groupby("Date", as_index=False)["Buy_Hold_Value"].sum()
)

# âœ… Plot with Plotly
fig = px.line(
    portfolio_summary,
    x="Date",
    y="Buy_Hold_Value",
    title="Buy_Hold_Value Over Time",
    labels={"Date": "Date", "Buy_Hold_Value": "Buy_Hold_Value"},
    markers=True
)

fig.update_traces(line=dict(width=2))
fig.update_layout(width=1000,   # ðŸ”‘ width
                  height=500)    # ðŸ”‘ height

fig.show()

# %%
final_df

# %%
old_df = final_df[~((final_df['Date']>'2025-11-30') & (final_df['Ticker']=='GOLDBEES'))]
old_df

# %%
np.sort(old_df['Ticker'].unique())

# %%
df = fetch_truedata_history(
    ticker_list = ['GOLDBEES', 'MOGSEC'],
    duration = '5 Y',
    bar_size = 'EOD',
    sleep_time= 0.1
)[0]
df = df[["Date","Ticker", "Open", "Close"]]
df['%change'] = df['Close'].pct_change()
# February rebalancing period
df = df[(df['Date'] >= '2025-12-01') & (df['Date'] <= '2026-02-28')]
# df.to_excel('C:\\Users\\Admin\\Momentum\\Automating Momentum True Data\\Trials\\nse200_Nifty_200_2025_Aug_nse200_nse200_nse200_nse200_nse200_returns.xlsx', index=False)
df

# %%
# February 2026 hedge weights: 10% GOLDBEES and 15% MOGSEC
ticker_weights = {'GOLDBEES':0.10, 'MOGSEC':0.15}
factor = 51.2140199725867

ticker_value = {ticker: weight * factor for ticker, weight in ticker_weights.items()}
ticker_value

# %%
df['BaseValue'] = df['Ticker'].map(ticker_value)
# Assign values
df['Value'] = df['Ticker'].map(ticker_value)
# Convert %change to numeric (if needed)
df['%change'] = pd.to_numeric(df['%change'])
# Sort (important for cumprod)
df = df.sort_values(['Ticker', 'Date'])

# Daily growth factor
df['ret_factor'] = 1 + df['%change']

# Cumulative factor per ticker
df['cum_factor'] = df.groupby('Ticker')['ret_factor'].cumprod()

# FINAL DAILY VALUE
df['Value_On_Date'] = df['BaseValue'] * df['cum_factor']

df = df[['Date', 'Ticker', 'Open', 'Close', 'Value_On_Date', '%change']].rename(columns={'Value_On_Date':'Buy_Hold_Value'})
df

# %%
conc_df = pd.concat([old_df, df])
conc_df

# %%
import plotly.express as px

# âœ… Group by Date and calculate total portfolio value
portfolio_summary = (
    conc_df.groupby("Date", as_index=False)["Buy_Hold_Value"].sum()
)
# âœ… Plot with Plotly
fig = px.line(
    portfolio_summary,
    x="Date",
    y="Buy_Hold_Value",
    title="Buy_Hold_Value Over Time",
    labels={"Date": "Date", "Buy_Hold_Value": "Buy_Hold_Value"},
    markers=True
)

fig.update_traces(line=dict(width=2))
fig.update_layout(width=1000,   # ðŸ”‘ width
                  height=500)    # ðŸ”‘ height
fig.show()

# %%
# Momentum/Automating Momentum True Data/Trials/Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx

# %%
conc_df.to_excel('C:\\Users\\anike\\Desktop\\Ocean_dev\\Momentum Handover\\Momentum Handover\\Trials\\Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx', index=False)
# \Trials

# %%
nse = fetch_truedata_history(
    ticker_list = ['Nifty 500'],
    duration = '5 Y',
    bar_size = 'EOD',
    sleep_time= 0.1
)[0]
nse = nse[["Date", "Close"]].rename(columns={'Close':'Buy_Hold_Value'})
nse['%change'] = nse['Buy_Hold_Value'].pct_change()
nse = nse[nse['Date'] >= '2023-04-01']
nse.to_excel('Trials\\nse500_Nifty_500_2025_Apr_nse500_nse500_nse500_nse500_nse500_returns.xlsx', index=False)
nse

# %%
conc_df

