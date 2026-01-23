import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import os

# Set Page Config
st.set_page_config(
    page_title="Momentum Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Custom CSS for Dark Glassy Theme ---
st.markdown("""
    <style>
    /* Main Background */
    .stApp {
        background-color: #0e1117;
        background-image: linear-gradient(315deg, #0e1117 0%, #161b22 74%);
    }

    /* Glassy Containers */
    .glassy-container {
        background: rgba(255, 255, 255, 0.05);
        border-radius: 16px;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 20px;
        margin-bottom: 20px;
    }

    /* Typography */
    h1, h2, h3, h4, h5, h6, p, label {
        color: #e6e6e6 !important;
        font-family: 'Inter', sans-serif;
    }
    
    /* Metrics */
    [data-testid="stMetricValue"] {
        color: #00e676 !important;
    }

    /* Tables */
    .dataframe {
        background-color: transparent !important;
        color: #e6e6e6 !important;
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background-color: rgba(22, 27, 34, 0.95);
        border-right: 1px solid rgba(255, 255, 255, 0.1);
    }
    </style>
""", unsafe_allow_html=True)


# --- Data Processing Logic (Adapted from PnL.ipynb) ---
@st.cache_data
def load_and_process_data(file_path):
    if not os.path.exists(file_path):
        return None, None
    
    df = pd.read_excel(file_path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values(["Ticker", "Date"])
    df["YearMonth"] = df["Date"].dt.to_period("M")

    # --- Ensure Quantity Column Exists ---
    if "Quantity" not in df.columns:
        # Infer Quantity = Buy_Hold_Value / Close
        # Round it to avoid floating point noise causing false trade signals
        if "Close" in df.columns and "Buy_Hold_Value" in df.columns:
            df["Quantity"] = (df["Buy_Hold_Value"] / df["Close"]).round(4)
        else:
            # Fallback if Close is also missing (unlikely based on file inspection)
            df["Quantity"] = 1

    # --- Identify Trades ---
    # Logic: New trade if month gap > 1 OR quantity changes
    df_month = df.drop_duplicates(subset=["Ticker", "YearMonth"]).sort_values(["Ticker", "YearMonth"])
    
    def get_trade_id(g):
        diff_months = g["YearMonth"].diff().apply(lambda x: x.n if pd.notna(x) else 1)
        # 1. First row is new trade
        # 2. Month gap > 1 is new trade
        # 3. Quantity change is new trade
        # Note: Using rounded quantity for comparison to be safe
        qty = g["Quantity"]
        new_trade = (diff_months.isna()) | (diff_months > 1) | (qty != qty.shift(1))
        return new_trade.cumsum()

    df_month["trade_id"] = df_month.groupby("Ticker", group_keys=False).apply(get_trade_id)
    
    # Merge trade_id back to daily data based on YearMonth
    # Note: This assigns the trade_id of the month to all days in that month
    df = df.merge(df_month[["Ticker", "YearMonth", "trade_id"]], on=["Ticker", "YearMonth"], how="left")

    # --- Determine Buy/Sell Dates & Status ---
    # For each trade_id, First Date is Buy Date.
    # Last Date is Sell Date (if closed) or Current Date (if open).
    # To determine if Open: Check if Last Date == Dataset's overall Max Date.
    
    dataset_max_date = df["Date"].max()
    
    trades = df.groupby(["Ticker", "trade_id"]).agg(
        Entry_Date=("Date", "min"),
        Last_Date=("Date", "max"),
        Entry_Price=("Close", "first"), # Approx, usually Buy_Price column is better if available
        Current_Value=("Buy_Hold_Value", "last"),
        Quantity=("Quantity", "last"),
        Buy_Hold_Value_Start=("Buy_Hold_Value", "first"), # Value at start of this specific trade segment
        Buy_Hold_Value_End=("Buy_Hold_Value", "last") # Value at end
    ).reset_index()

    # Calculate Returns
    # Return = (End Value - Start Value) / Start Value
    # This is "Contribution of this specific trade segment"
    trades["Return_Abs"] = trades["Buy_Hold_Value_End"] - trades["Buy_Hold_Value_Start"]
    trades["Return_Pct"] = (trades["Buy_Hold_Value_End"] / trades["Buy_Hold_Value_Start"]) - 1
    
    # Identify Active Trades
    # A trade is active if its Last_Date is the dataset_max_date
    trades["Is_Active"] = trades["Last_Date"] == dataset_max_date
    
    return trades, dataset_max_date

# --- Main App ---
st.title("🚀 Momentum Portfolio Dashboard")

# File Path (Relative to script or absolute)
# Assuming script is in 'Momentum Handover', data is in 'Trials'
DATA_PATH = os.path.join("Trials", "Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")

if not os.path.exists(DATA_PATH):
    st.error(f"Data file not found at: {DATA_PATH}. Please check the path.")
else:
    with st.spinner("Processing Data..."):
        trades, last_update_date = load_and_process_data(DATA_PATH)

    if trades is not None:
        st.caption(f"Last Data Update: {last_update_date.strftime('%d %B %Y')}")

        # --- Filter Active Trades ---
        active_holdings = trades[trades["Is_Active"]].copy()
        
        # Include explicit symbols if they are active (checking just in case they were filtered out or handled differently)
        # Logic already covers them if they are in the excel and active.
        
        # Metrics
        total_value = active_holdings["Current_Value"].sum()
        total_return_abs = active_holdings["Return_Abs"].sum()
        
        # Calculate Contribution % (Contribution to Total Portfolio Return)
        # Formula: (Individual Return / Total Portfolio Return) * 100
        if total_return_abs != 0:
            active_holdings["Contribution_Pct_Total_Return"] = (active_holdings["Return_Abs"] / total_return_abs) * 100
        else:
            active_holdings["Contribution_Pct_Total_Return"] = 0

        # Display Metrics in Glassy Container
        st.markdown('<div class="glassy-container">', unsafe_allow_html=True)
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Portfolio Value", f"₹ {total_value:,.2f}")
        col2.metric("Total Active Returns", f"₹ {total_return_abs:,.2f}")
        col3.metric("Active Holdings", len(active_holdings))
        st.markdown('</div>', unsafe_allow_html=True)

        # --- Layout: Table & Pie Chart ---
        col_table, col_chart = st.columns([1.8, 1])

        with col_table:
            st.markdown("### 📋 Current Portfolio Holdings")
            st.markdown('<div class="glassy-container">', unsafe_allow_html=True)
            
            # Prepare Table Data
            # Requested Columns: Entry Date, Symbol Name, Entry Price, Profit/Loss, % Contribution
            table_df = active_holdings[[
                "Entry_Date", 
                "Ticker", 
                "Entry_Price", 
                "Return_Abs", 
                "Contribution_Pct_Total_Return"
            ]].copy()
            
            table_df["Entry_Date"] = table_df["Entry_Date"].dt.strftime('%Y-%m-%d')
            table_df["Entry_Price"] = table_df["Entry_Price"].map('₹ {:,.2f}'.format)
            table_df["Return_Abs"] = table_df["Return_Abs"].map('₹ {:,.2f}'.format)
            table_df["Contribution_Pct_Total_Return"] = table_df["Contribution_Pct_Total_Return"].map('{:,.2f}%'.format)
            
            st.dataframe(
                table_df.rename(columns={
                    "Entry_Date": "Entry Date",
                    "Ticker": "Symbol Name",
                    "Entry_Price": "Entry Price",
                    "Return_Abs": "Profit/Loss",
                    "Contribution_Pct_Total_Return": "% Contribution (Return)"
                }),
                use_container_width=True,
                hide_index=True,
                height=500
            )
            st.markdown('</div>', unsafe_allow_html=True)

        with col_chart:
            st.markdown("### 🥧 Asset Allocation")
            st.markdown('<div class="glassy-container">', unsafe_allow_html=True)
            
            # Pie Chart
            fig = px.pie(
                active_holdings, 
                values='Current_Value', 
                names='Ticker', 
                title='Contribution by Asset Value',
                hole=0.4,
                color_discrete_sequence=px.colors.sequential.Tealgrn
            )
            
            # Toggle Button for Legend
            show_legend = st.checkbox('Show Chart Legend', value=True)
            
            fig.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#e6e6e6'),
                showlegend=show_legend,
                legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="center", x=0.5)
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            
            st.plotly_chart(fig, use_container_width=True)
            st.markdown('</div>', unsafe_allow_html=True)

