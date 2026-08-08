"""
Test script to discover correct TrueData symbols for:
  - Nifty Smallcap 250
  - Nifty 50:25:25 Multi Cap

Tries multiple candidate symbol strings and prints which ones return data.
"""

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj

# Candidate symbols to test for each index
CANDIDATES = {
    "Nifty_Smallcap_250": [
        "NIFTY SMALLCAP 250",
        "NIFTY SMALLCAP250",
        "NIFTYSMALLCAP250",
        "NIFTY SMALL CAP 250",
        "NIFTY SMALL CAP250",
        "NIFTY SC 250",
        "NIFTY SC250",
        "NIFTYSMALLCAP",
        "NIFTY SMALLCAP",
        "NIFTY SMALL CAP",
        "NIFTY250",
    ],
    "Nifty_50_25_25_Multi_Cap": [
        "NIFTY MULTI CAP 50:25:25",
        "NIFTY MULTICAP 50:25:25",
        "NIFTY MULTICAP 502525",
        "NIFTY MULTICAP",
        "NIFTY MULTI CAP",
        "NIFTY 502525",
        "NIFTY50",
        "NIFTY MULTICAP 50 25 25",
        "NIFTY MULTI CAP 50 25 25",
    ],
}


def test_symbol(td_obj, symbol: str):
    """Try to fetch ~30 days of EOD data for a symbol."""
    try:
        raw = td_obj.get_historic_data([symbol], duration="30 D", bar_size="EOD")
        if raw is None:
            return False, "None response"
        if isinstance(raw, list):
            if not raw:
                return False, "empty list"
            import pandas as pd
            df = pd.DataFrame(raw)
        else:
            df = raw.copy() if hasattr(raw, "copy") else raw
        if hasattr(df, "empty") and df.empty:
            return False, "empty DataFrame"
        return True, f"{len(df)} rows"
    except Exception as exc:
        return False, str(exc)


def main():
    print("Connecting to TrueData...")
    try:
        td_obj = get_td_obj()
    except Exception as exc:
        print(f"Connection failed: {exc}")
        return

    for display_name, symbols in CANDIDATES.items():
        print("\n" + "=" * 60)
        print(f"Testing: {display_name}")
        print("=" * 60)
        found_any = False
        for sym in symbols:
            ok, info = test_symbol(td_obj, sym)
            status = "✅ FOUND" if ok else "❌"
            print(f"  {status}  {sym:<35} -> {info}")
            if ok:
                found_any = True
        if not found_any:
            print("  (none of the candidates returned data)")

    print("\n" + "=" * 60)
    print("Symbol discovery complete.")
    print("=" * 60)


if __name__ == "__main__":
    main()
