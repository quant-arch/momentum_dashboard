import pandas as pd
files=[
 r'C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials\Nifty_500_2025_Apr_20_stocks_results_GoldSilverDebt_buy&hold_returns.xlsx',
 r'C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Trials\Nifty_500_2025_Apr_20_stocks_results_gold_buy&hold_returns.xlsx',
 r'C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\Momentum_Maxfolio.xlsx'
]
for f in files:
    try:
        df=pd.read_excel(f)
        has='LIQUIDCASE' in df['Ticker'].astype(str).unique()
        print(f + ' => has LIQUIDCASE: ' + str(has))
        if has:
            print(df[df['Ticker']=='LIQUIDCASE'].head().to_string(index=False))
    except Exception as e:
        print('ERROR reading ' + f + ' ' + str(e))
