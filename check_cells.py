import json
with open('Momentum prod from 11th Nov_mar_rebalance.ipynb', encoding='utf-8') as f:
    nb = json.load(f)

for i, cell in enumerate(nb['cells']):
    if cell['cell_type'] == 'code':
        source = "".join(cell['source'])
        print(f"--- Cell {i} ---")
        print(source[:150] + ("..." if len(source) > 150 else ""))
