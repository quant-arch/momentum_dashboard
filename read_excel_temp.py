import pandas as pd

try:
    file_path = r'C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials\Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx'
    df = pd.read_excel(file_path)
    df['Date'] = pd.to_datetime(df['Date'])
    
    # Check what columns exist
    # print("Columns:", df.columns.tolist())
    
    # Look at 2026-02-27
    df_date = df[df['Date'] == '2026-02-27']
    
    if df_date.empty:
        print("No data found for 2026-02-27")
    else:
        # print(df_date.head())
        if 'Total_Portfolio_Value' in df.columns:
            print("Total_Portfolio_Value on 2026-02-27 (first row):", df_date['Total_Portfolio_Value'].iloc[0])
            
        print("Sum of Buy_Hold_Value on 2026-02-27:", df_date['Buy_Hold_Value'].sum())
except Exception as e:
    print("Error:", e)
