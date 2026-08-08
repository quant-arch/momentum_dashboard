import json
import os

files_to_update = [
    'Momentum prod from 11th Nov_march_rebalance.ipynb',
    'Momentum prod from 11th Nov_mar_rebalance.ipynb'
]

cell_11_code = """import plotly.express as px

# Combine base portfolio with dynamically built hedge book
conc_df = pd.concat([old_df, df])
conc_df = conc_df[conc_df['Date'] <= pd.Timestamp.today().normalize()]

# Save output
conc_df.to_excel('Momentum_Maxfolio.xlsx', index=False)
print("Saved final Maxfolio to Momentum_Maxfolio.xlsx")

# Plot Total Portfolio Value
portfolio_summary = conc_df.groupby("Date", as_index=False)["Buy_Hold_Value"].sum()
fig = px.line(
    portfolio_summary,
    x="Date",
    y="Buy_Hold_Value",
    title="Total Portfolio Value (Inception to Present)",
    labels={"Date": "Date", "Buy_Hold_Value": "Buy_Hold_Value"},
    markers=True
)
fig.update_traces(line=dict(width=2))
fig.update_layout(width=1000, height=500)
fig.show()
"""

for target_file in files_to_update:
    if not os.path.exists(target_file):
        continue
        
    with open(target_file, encoding='utf-8') as f:
        nb = json.load(f)

    # We will slice the notebook to keep only up to cell 10, then add cell 11
    # Check if cell 10 exists, if not, we shouldn't slice blindly.
    if len(nb['cells']) > 10:
        nb['cells'] = nb['cells'][:11]
        
        # Create cell 11
        new_cell = {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [line + "\\n" for line in cell_11_code.split("\\n")]
        }
        if new_cell["source"]:
            new_cell["source"][-1] = new_cell["source"][-1].rstrip("\\n")
            
        nb['cells'].append(new_cell)

    with open(target_file, 'w', encoding='utf-8') as f:
        json.dump(nb, f, indent=1)

print("Successfully cleaned notebooks!")
