content = open('run_old.py', encoding='utf-8').read()
content = content.replace(r'"Stocks/Nifty_500_2025_Apr_20_stocks_results/master_momentum_summary.xlsx"', r'r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2\Stocks_old\Nifty_500_2025_Apr_20_stocks_results\master_momentum_summary.xlsx"')
with open('run_old.py', 'w', encoding='utf-8') as f:
    f.write(content)
