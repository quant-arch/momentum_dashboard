import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_excel('Momentum_Maxfolio_NEW.xlsx')
df['Date'] = pd.to_datetime(df['Date'])

portfolio = df.groupby('Date')['Buy_Hold_Value'].sum().reset_index()

plt.figure(figsize=(12, 6))
plt.plot(portfolio['Date'], portfolio['Buy_Hold_Value'], marker='o', linestyle='-', linewidth=2)
plt.title('Total Portfolio Value (Inception: Nov 11, 2025 - Present)')
plt.xlabel('Date')
plt.ylabel('Buy Hold Value')
plt.grid(True)
plt.tight_layout()
plt.savefig('portfolio_curve.png', dpi=300)
print('Plot saved to portfolio_curve.png')
