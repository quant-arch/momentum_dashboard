import numpy as np
import pandas as pd
from datetime import datetime, timedelta
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
    last_month_quantity = {}

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
        stock_data = stock_data[stock_data['Date']>='2025-11-11']
        
        # % change
        stock_data['%change'] = stock_data.groupby('Ticker')['Close'].pct_change()
        # Filter current month
        stock_data_flt = stock_data[
            (stock_data['Date'] >= curr_month_start) & (stock_data['Date'] <= curr_month_end)
        ].copy()

        print(stock_data_flt)

        # --- Portfolio allocation logic ---
        if len(last_month_value) == 0:
            # First month → allocate initial portfolio equally
            allocation_per_stock = initial_value / len(tickers)
            stock_allocations = {t: allocation_per_stock for t in tickers}
        else:
            # Continue portfolio
            stock_allocations = {t: last_month_value[t] for t in tickers if t in last_month_value}

            # Pool value of dropped stocks
            dropped_stocks = [t for t in last_month_value if t not in tickers]
            dropped_value = sum(last_month_value[t] for t in dropped_stocks)

            # New stocks → share the dropped value equally
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
            
            tkr_df = stock_data_flt[stock_data_flt['Ticker'] == tkr]
            if tkr_df.empty:
                continue

            buy_price = tkr_df.iloc[0]['Close']

            # Carry quantity if stock existed last month
            if tkr in last_month_quantity:
                quantity = last_month_quantity[tkr]
            else:
                quantity = init_value / buy_price
                
            stock_data_flt.loc[tkr_df.index, 'Buy_Price'] = buy_price
            stock_data_flt.loc[tkr_df.index, 'Quantity'] = quantity

        # --- Update last month values ---

        last_month_quantity = (
            stock_data_flt.groupby('Ticker')['Quantity'].last().to_dict()
        )
        
        last_month_value = (
            stock_data_flt.groupby('Ticker')['Buy_Hold_Value'].last().to_dict()
        )

        # --- Track total portfolio value ---
        stock_data_flt['Total_Portfolio_Value'] = (
            stock_data_flt.groupby('Date')['Buy_Hold_Value'].transform('sum')
        )

        df_lis.append(stock_data_flt)

    
    final_df = pd.concat(df_lis).reset_index(drop=True)

    # if output_file:
    #     final_df.to_excel(output_file, index=False)

    return final_df



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
    print(f"✅ Final output saved to: {output_file}")

    return final_df


#NSE500

final_df = prepare_and_process_portfolio(
    input_file="Stocks/Nifty_500_2025_Apr_20_stocks_results/master_momentum_summary.xlsx",
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

fig.show()

final_df

final_df

old_df = final_df[~((final_df['Date']>'2025-11-30') & (final_df['Ticker']=='GOLDBEES'))]
old_df

old_df['Ticker'].unique()

# Build hedge book with month rebalancing (Dec/Jan -> Feb -> Mar) starting after 2025-11-30
portfolio_end_date = pd.to_datetime(final_df['Date']).max()

# Use the last GOLDBEES value before Dec as the hedge book starting capital
hedge_start_factor = final_df[(final_df['Ticker'] == 'GOLDBEES') & (final_df['Date'] <= '2025-11-30')].copy()
# (Fallback if GOLDBEES leg doesn't exist for some reason)
if hedge_start_factor.empty:
    hedge_start_factor = 25.0
else:
    hedge_start_factor = hedge_start_factor.sort_values('Date')['Buy_Hold_Value'].iloc[-1]

# --- Dec 2025 to Jan 2026 hedge: GOLDBEES + SILVERBEES + MOGSEC (60/20/20 of hedge book) ---
df_decjan = fetch_truedata_history(
    ticker_list=['GOLDBEES', 'SILVERBEES', 'MOGSEC'],
    duration='5 Y',
    bar_size='EOD',
    sleep_time=0.1
)[0]
df_decjan = df_decjan[["Date", "Ticker", "Open", "Close"]].copy()
df_decjan = df_decjan[(df_decjan['Date'] >= '2025-12-01') & (df_decjan['Date'] <= '2026-01-31')].copy()
df_decjan['%change'] = df_decjan.groupby('Ticker')['Close'].pct_change()

ticker_weights_decjan = {'GOLDBEES': 0.60, 'SILVERBEES': 0.20, 'MOGSEC': 0.20}
ticker_value_decjan = {t: w * hedge_start_factor for t, w in ticker_weights_decjan.items()}
df_decjan['BaseValue'] = df_decjan['Ticker'].map(ticker_value_decjan)
df_decjan['%change'] = pd.to_numeric(df_decjan['%change'])
df_decjan = df_decjan.sort_values(['Ticker', 'Date'])
df_decjan['ret_factor'] = 1 + df_decjan['%change'].fillna(0)
df_decjan['cum_factor'] = df_decjan.groupby('Ticker')['ret_factor'].cumprod()
df_decjan['Value_On_Date'] = df_decjan['BaseValue'] * df_decjan['cum_factor']
df_decjan = df_decjan[['Date', 'Ticker', 'Open', 'Close', 'Value_On_Date', '%change']].rename(columns={'Value_On_Date': 'Buy_Hold_Value'})

# --- Feb 2026 hedge rebalance: sell SILVERBEES, rebalance hedge book to 40% GOLDBEES / 60% MOGSEC ---
feb_start = pd.Timestamp('2026-02-01')
feb_end = pd.Timestamp('2026-02-28')
df_feb = pd.DataFrame()
if portfolio_end_date >= feb_start:
    feb_factor = df_decjan.groupby('Date', as_index=False)['Buy_Hold_Value'].sum().sort_values('Date')['Buy_Hold_Value'].iloc[-1]
    df_feb = fetch_truedata_history(
        ticker_list=['GOLDBEES', 'MOGSEC'],
        duration='5 Y',
        bar_size='EOD',
        sleep_time=0.1
    )[0]
    df_feb = df_feb[["Date", "Ticker", "Open", "Close"]].copy()
    df_feb = df_feb[(df_feb['Date'] >= feb_start) & (df_feb['Date'] <= min(feb_end, portfolio_end_date))].copy()
    df_feb['%change'] = df_feb.groupby('Ticker')['Close'].pct_change()

    ticker_weights_feb = {'GOLDBEES': 0.40, 'MOGSEC': 0.60}
    ticker_value_feb = {t: w * feb_factor for t, w in ticker_weights_feb.items()}
    df_feb['BaseValue'] = df_feb['Ticker'].map(ticker_value_feb)
    df_feb['%change'] = pd.to_numeric(df_feb['%change'])
    df_feb = df_feb.sort_values(['Ticker', 'Date'])
    df_feb['ret_factor'] = 1 + df_feb['%change'].fillna(0)
    df_feb['cum_factor'] = df_feb.groupby('Ticker')['ret_factor'].cumprod()
    df_feb['Value_On_Date'] = df_feb['BaseValue'] * df_feb['cum_factor']
    df_feb = df_feb[['Date', 'Ticker', 'Open', 'Close', 'Value_On_Date', '%change']].rename(columns={'Value_On_Date': 'Buy_Hold_Value'})

# --- Mar 2026 hedge rebalance: transfer MOGSEC holding to LIQUIDCASE ---
mar_start = pd.Timestamp('2026-03-01')
df_mar = pd.DataFrame()
if portfolio_end_date >= mar_start and not df_feb.empty:
    feb_last_date = df_feb['Date'].max()
    feb_last = df_feb[df_feb['Date'] == feb_last_date].set_index('Ticker')['Buy_Hold_Value'].to_dict()
    gold_base_mar = feb_last.get('GOLDBEES', 0.0)
    liquid_base_mar = feb_last.get('MOGSEC', 0.0)

    df_mar = fetch_truedata_history(
        ticker_list=['GOLDBEES', 'LIQUIDCASE'],
        duration='5 Y',
        bar_size='EOD',
        sleep_time=0.1
    )[0]
    df_mar = df_mar[["Date", "Ticker", "Open", "Close"]].copy()
    df_mar = df_mar[(df_mar['Date'] >= mar_start) & (df_mar['Date'] <= portfolio_end_date)].copy()
    df_mar['%change'] = df_mar.groupby('Ticker')['Close'].pct_change()

    ticker_value_mar = {'GOLDBEES': gold_base_mar, 'LIQUIDCASE': liquid_base_mar}
    df_mar['BaseValue'] = df_mar['Ticker'].map(ticker_value_mar)
    df_mar['%change'] = pd.to_numeric(df_mar['%change'])
    df_mar = df_mar.sort_values(['Ticker', 'Date'])
    df_mar['ret_factor'] = 1 + df_mar['%change'].fillna(0)
    df_mar['cum_factor'] = df_mar.groupby('Ticker')['ret_factor'].cumprod()
    df_mar['Value_On_Date'] = df_mar['BaseValue'] * df_mar['cum_factor']
    df_mar = df_mar[['Date', 'Ticker', 'Open', 'Close', 'Value_On_Date', '%change']].rename(columns={'Value_On_Date': 'Buy_Hold_Value'})

df = pd.concat([df_decjan, df_feb, df_mar], ignore_index=True).sort_values(['Date', 'Ticker'])
df



# Hedge rebalancing is computed in the previous cell; quick sanity view:
df[['Date', 'Ticker', 'Buy_Hold_Value']].head()

# (No-op) Hedge valuation already computed above.
df.tail()

# df

df['Buy_Value'] = df.groupby('Ticker')['Buy_Hold_Value'].transform('first')
df['Buy_Price'] = df.groupby('Ticker')['Close'].transform('first')
df['Quantity'] = df['Buy_Value'] / df['Buy_Price']
df

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
fig.show()

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

conc_df.to_excel('Momentum_Maxfolio.xlsx', index=False)