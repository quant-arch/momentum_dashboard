"""
Inspect available methods on the TrueData TD_hist object
and test symbol-list retrieval.
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj

td_obj = get_td_obj()

print("\n" + "=" * 60)
print("TD_hist methods / attributes")
print("=" * 60)
for attr in sorted(dir(td_obj)):
    if not attr.startswith("_"):
        print(f"  {attr}")

# Look for symbol-related methods
symbol_methods = [m for m in dir(td_obj) if "symbol" in m.lower() or "sym" in m.lower()]
print("\n" + "=" * 60)
print("Symbol-related methods")
print("=" * 60)
for m in symbol_methods:
    print(f"  {m}")

# Try calling likely methods
likely = ["get_symbols", "getSymbols", "symbol_list", "symbols", "getSymbolList",
          "getAllSymbols", "get_all_symbols", "get_symbol_list", "getMasterSymbols"]
print("\n" + "=" * 60)
print("Testing likely symbol-list methods")
print("=" * 60)
for m in likely:
    if hasattr(td_obj, m):
        try:
            result = getattr(td_obj, m)()
            print(f"\n{m}() -> type={type(result).__name__}, len={len(result) if hasattr(result, '__len__') else 'N/A'}")
            if isinstance(result, list):
                print(f"  First 20: {result[:20]}")
            elif isinstance(result, dict):
                print(f"  Keys: {list(result.keys())[:20]}")
            elif hasattr(result, "columns"):
                print(f"  Columns: {list(result.columns)}")
                print(f"  Head:\n{result.head()}")
            else:
                print(f"  Value: {result}")
        except Exception as exc:
            print(f"\n{m}() -> ERROR: {exc}")
