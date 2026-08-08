"""
Brute-force search for correct TrueData symbols for:
  - Nifty Smallcap 250
  - Nifty 50:25:25 Multi Cap

Includes pandas 3.0 monkey-patch and a wide range of naming variations.
"""

import pandas as pd

# Monkey-patch BEFORE any truedata import
if not hasattr(pd.DataFrame, "timestamp"):
    def _get_df_timestamp(self):
        return self["timestamp"] if "timestamp" in self.columns else None
    def _set_df_timestamp(self, value):
        self["timestamp"] = value
    pd.DataFrame.timestamp = property(_get_df_timestamp, _set_df_timestamp)

import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj


def test_symbol(td_obj, symbol: str):
    """Quick 30-day test fetch. Returns (success, row_count_or_error)."""
    try:
        raw = td_obj.get_historic_data([symbol], duration="30 D", bar_size="EOD")
        if raw is None:
            return False, "None"
        if isinstance(raw, list):
            if not raw:
                return False, "empty list"
            df = pd.DataFrame(raw)
        else:
            df = raw.copy() if hasattr(raw, "copy") else raw
        if hasattr(df, "empty") and df.empty:
            return False, "empty DataFrame"
        return True, len(df)
    except Exception as exc:
        return False, str(exc)


def main():
    print("Connecting to TrueData...")
    td_obj = get_td_obj()
    print("Connected.\n")

    # Known working index symbols for reference
    known_good = ["NIFTY 50", "NIFTY 500", "NIFTY MIDCAP 150"]
    print("=" * 60)
    print("Verifying known-good symbols")
    print("=" * 60)
    for sym in known_good:
        ok, info = test_symbol(td_obj, sym)
        status = "✅" if ok else "❌"
        print(f"  {status} {sym:<35} -> {info}")

    # Smallcap 250 candidates - many variations
    smallcap_candidates = [
        "NIFTY SMALLCAP 250",
        "NIFTY SMALL CAP 250",
        "NIFTY SMALLCAP250",
        "NIFTY SMALLCAP",
        "NIFTY SMALL CAP",
        "NIFTY250",
        "NIFTY 250",
        "NIFTY SC 250",
        "NIFTY SC250",
        "NIFTY-SMALLCAP-250",
        "NIFTY_SMALLCAP_250",
        "SMALLCAP250",
        "SMALLCAP 250",
        "NIFTY SC",
        "NIFTY SMLCAP 250",
        "NIFTY SMLCAP250",
        "NIFTYSMALLCAP250",
        "NIFTYSMALLCAP",
        "NSE SMALLCAP 250",
        "NSE SMALLCAP250",
        "NIFTY SMALL CAP 250 TR",
        "NIFTY SMALLCAP 250 TR",
    ]

    # Multi Cap 50:25:25 candidates - many variations
    multicap_candidates = [
        "NIFTY MULTI CAP 50:25:25",
        "NIFTY MULTICAP 50:25:25",
        "NIFTY MULTI CAP",
        "NIFTY MULTICAP",
        "NIFTY MULTICAP 502525",
        "NIFTY MULTI CAP 502525",
        "NIFTY 502525",
        "NIFTY MULTICAP 50 25 25",
        "NIFTY MULTI CAP 50 25 25",
        "NIFTY-MULTICAP-50-25-25",
        "NIFTY_MULTICAP_50_25_25",
        "MULTICAP 50:25:25",
        "MULTI CAP 50:25:25",
        "NIFTY MULTICAP 50-25-25",
        "NIFTY MULTI CAP 50-25-25",
        "NIFTY 50 25 25",
        "NIFTY MULTICAP NSE",
        "NIFTY MULTI CAP NSE",
        "NSE MULTICAP 50:25:25",
        "NSE MULTI CAP 50:25:25",
        "NIFTY MULTI CAP 50:25:25 TR",
        "NIFTY MULTICAP 50:25:25 TR",
        "NIFTY500 MULTICAP 50:25:25",
        "NIFTY 500 MULTICAP 50:25:25",
    ]

    print("\n" + "=" * 60)
    print("Testing Smallcap 250 candidates")
    print("=" * 60)
    smallcap_found = []
    for sym in smallcap_candidates:
        ok, info = test_symbol(td_obj, sym)
        status = "✅" if ok else "❌"
        print(f"  {status} {sym:<45} -> {info}")
        if ok:
            smallcap_found.append(sym)

    print("\n" + "=" * 60)
    print("Testing Multi Cap 50:25:25 candidates")
    print("=" * 60)
    multicap_found = []
    for sym in multicap_candidates:
        ok, info = test_symbol(td_obj, sym)
        status = "✅" if ok else "❌"
        print(f"  {status} {sym:<45} -> {info}")
        if ok:
            multicap_found.append(sym)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Smallcap 250 working symbols: {smallcap_found if smallcap_found else 'NONE FOUND'}")
    print(f"Multi Cap working symbols:    {multicap_found if multicap_found else 'NONE FOUND'}")


if __name__ == "__main__":
    main()
