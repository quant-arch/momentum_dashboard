import pandas as pd
import numpy as np

def compare():
    try:
        old_df = pd.read_excel('OLD.xlsx')
        new_df = pd.read_excel('Momentum_Maxfolio_NEW.xlsx')
        
        old_df['Date'] = pd.to_datetime(old_df['Date'])
        new_df['Date'] = pd.to_datetime(new_df['Date'])
        
        old_df = old_df[old_df['Date'] <= '2026-04-30'].copy()
        new_df = new_df[new_df['Date'] <= '2026-04-30'].copy()
        
        cols_to_round = ['Buy_Hold_Value', 'Quantity', 'Buy_Price']
        for col in cols_to_round:
            if col in old_df.columns:
                old_df[col] = old_df[col].round(4)
            if col in new_df.columns:
                new_df[col] = new_df[col].round(4)
                
        print(f"OLD shape up to 2026-04-30: {old_df.shape}")
        print(f"NEW shape up to 2026-04-30: {new_df.shape}")
        
        print(f"OLD Total Portfolio Value on 2026-04-30: {old_df[old_df['Date'] == '2026-04-30']['Buy_Hold_Value'].sum():.2f}")
        print(f"NEW Total Portfolio Value on 2026-04-30: {new_df[new_df['Date'] == '2026-04-30']['Buy_Hold_Value'].sum():.2f}")
        
        old_grouped = old_df.groupby(['Date', 'Ticker'])['Buy_Hold_Value'].sum().reset_index()
        new_grouped = new_df.groupby(['Date', 'Ticker'])['Buy_Hold_Value'].sum().reset_index()
        
        merged = pd.merge(old_grouped, new_grouped, on=['Date', 'Ticker'], suffixes=('_old', '_new'), how='outer')
        merged['diff'] = np.abs(merged['Buy_Hold_Value_old'] - merged['Buy_Hold_Value_new'])
        diffs = merged[merged['diff'] > 0.01]
        
        print(f"\\nFound {len(diffs)} differences > 0.01 in Buy_Hold_Value")
        if len(diffs) > 0:
            print("First 5 differences:")
            print(diffs.head())
        else:
            print("The outputs are identical up to 2026-04-30!")
            
    except Exception as e:
        print(f"Error reading files: {e}")

if __name__ == '__main__':
    compare()
