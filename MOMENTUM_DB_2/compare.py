import pandas as pd
import numpy as np

def calculate_metrics(file_path):
    try:
        df = pd.read_excel(file_path)
    except FileNotFoundError:
        return {
            "Total Return (%)": np.nan,
            "CAGR (%)": np.nan,
            "Annualized Volatility (%)": np.nan,
            "Max Drawdown (%)": np.nan
        }
    
    df_daily = df.drop_duplicates(subset=['Date'])[['Date', 'Total_Portfolio_Value']].copy()
    df_daily.sort_values('Date', inplace=True)
    df_daily.set_index('Date', inplace=True)
    
    start_val = df_daily['Total_Portfolio_Value'].iloc[0]
    end_val = df_daily['Total_Portfolio_Value'].iloc[-1]
    days = (df_daily.index[-1] - df_daily.index[0]).days
    years = days / 365.25
    cagr = (end_val / start_val) ** (1 / years) - 1
    total_return = (end_val / start_val) - 1
    
    df_daily['Daily_Return'] = df_daily['Total_Portfolio_Value'].pct_change()
    volatility = df_daily['Daily_Return'].std() * np.sqrt(252)
    
    cumulative_max = df_daily['Total_Portfolio_Value'].cummax()
    drawdown = (df_daily['Total_Portfolio_Value'] - cumulative_max) / cumulative_max
    max_drawdown = drawdown.min()
    
    return {
        "Total Return (%)": total_return * 100,
        "CAGR (%)": cagr * 100,
        "Annualized Volatility (%)": volatility * 100,
        "Max Drawdown (%)": max_drawdown * 100
    }

metrics_6m = calculate_metrics(r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials\Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")
metrics_1yr = calculate_metrics(r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials\Nifty_500_2025_Apr_1yr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx")

df_comparison = pd.DataFrame({'6 Month Lookback': metrics_6m, '1 Year Lookback': metrics_1yr})
print(df_comparison.to_markdown())
