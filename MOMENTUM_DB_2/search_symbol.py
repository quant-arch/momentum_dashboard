import sys
import os

sys.path.insert(0, r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2")
from discover_and_fetch_missing_indices import get_all_symbols, search_symbols
from truedata_connector import get_td_obj

td = get_td_obj()
all_symbols = get_all_symbols(td)

print(f"Total symbols found: {len(all_symbols) if all_symbols else 0}")
if all_symbols:
    hits = search_symbols(all_symbols, ["HYBRID"])
    print(f"Candidates for HYBRID: {hits}")
    
    hits2 = search_symbols(all_symbols, ["COMPOSITE", "DEBT"])
    print(f"Candidates for COMPOSITE DEBT: {hits2}")
