"""
Test script to verify TrueData symbols for VEDL demerger entities.
Tries multiple possible symbol names for each new company.
"""
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import sys
import time
import logging

sys.path.insert(0, r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2")
from truedata_connector import get_td_obj

logging.basicConfig(level=logging.WARNING)  # suppress noise

# ---------------------------------------------------------------------------
# Symbol candidates to test
# Each entry: (company_name, [candidate_symbols_to_try])
# ---------------------------------------------------------------------------
CANDIDATES = {
    "Vedanta Aluminium Metal Ltd": ["VAML", "VEDANTALUM", "VEDAL", "VEDANTAALUM"],
    "Vedanta Iron and Steel Ltd":  ["VISL", "VEDSL", "VEDANTSTEEL", "VEDANTAIRON"],
    "Talwandi Sabo Power Ltd":     ["VEDPOWER", "TSPL", "TALWANDISABO", "VEDANTAPOWER", "VEDPWR"],
    "Malco Energy Ltd":            ["VOGL", "MALCO", "MALCOENERGY", "VEDANTAOG", "MALCOIL"],
}

# Also re-verify VEDL itself
CANDIDATES["Vedanta Ltd (original)"] = ["VEDL"]

def test_symbol(td_hist, symbol: str) -> dict:
    """Try fetching 5-day EOD for a symbol. Return result info."""
    try:
        df = td_hist.get_historic_data([symbol], duration="5 D", bar_size="EOD")
        if df is None or (hasattr(df, "empty") and df.empty):
            return {"symbol": symbol, "status": "NO_DATA", "rows": 0, "last_close": None}
        rows = len(df)
        close_col = next((c for c in ["close", "Close"] if c in df.columns), None)
        last_close = float(df[close_col].iloc[-1]) if close_col else "N/A"
        return {"symbol": symbol, "status": "OK", "rows": rows, "last_close": last_close}
    except Exception as e:
        return {"symbol": symbol, "status": f"ERROR: {e}", "rows": 0, "last_close": None}


def main():
    print("\n" + "="*65)
    print("  TrueData Symbol Probe — VEDL Demerger Entities")
    print("="*65)

    td_hist = get_td_obj()
    print()

    results = {}
    for company, symbols in CANDIDATES.items():
        print(f"\n" + "-"*60)
        print(f"  Company : {company}")
        print("-"*60)
        company_results = []
        for sym in symbols:
            res = test_symbol(td_hist, sym)
            company_results.append(res)
            status_str = res["status"]
            if res["status"] == "OK":
                print(f"  [OK]  {sym:<20}  rows={res['rows']}  last_close={res['last_close']}")
            elif res["status"] == "NO_DATA":
                print(f"  [--]  {sym:<20}  (connected but returned empty data)")
            else:
                print(f"  [XX]  {sym:<20}  {status_str}")
            time.sleep(0.3)
        results[company] = company_results

    # Summary
    print("\n" + "="*65)
    print("  SUMMARY — Valid symbols found")
    print("="*65)
    for company, res_list in results.items():
        valid = [r["symbol"] for r in res_list if r["status"] == "OK"]
        no_data = [r["symbol"] for r in res_list if r["status"] == "NO_DATA"]
        if valid:
            print(f"  {company}")
            print(f"    -> VALID    : {valid}")
            if no_data:
                print(f"    -> NO_DATA  : {no_data}")
        elif no_data:
            print(f"  {company}")
            print(f"    -> Connected but empty: {no_data}  (symbol exists, no history yet?)")
        else:
            print(f"  {company}")
            print(f"    -> [NONE FOUND] None of {[r['symbol'] for r in res_list]} found in TrueData")
    print()


if __name__ == "__main__":
    main()
