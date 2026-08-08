import sys
import os
import pandas as pd
from datetime import datetime
import logging

if not hasattr(pd.DataFrame, "timestamp"):
    def _get_df_timestamp(self):
        return self["timestamp"] if "timestamp" in self.columns else None
    def _set_df_timestamp(self, value):
        self["timestamp"] = value
    pd.DataFrame.timestamp = property(_get_df_timestamp, _set_df_timestamp)

SCRIPT_DIR = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\MOMENTUM_DB_2"
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj

td = get_td_obj()

candidates = [
    "Nifty 50 Hybrid Composite Debt 65:35 Index",
    "NIFTY 50 HYBRID COMPOSITE DEBT 65:35 INDEX"
]

for sym in candidates:
    print(f"Testing '{sym}'")
    try:
        raw = td.get_historic_data([sym], duration="30 D", bar_size="EOD")
        if raw is not None:
            if isinstance(raw, list) and len(raw) > 0:
                print(f"SUCCESS: {sym} (List of length {len(raw)})")
            elif not isinstance(raw, list) and not raw.empty:
                print(f"SUCCESS: {sym} (DataFrame of length {len(raw)})")
            else:
                print(f"Empty data for '{sym}'")
        else:
            print(f"None returned for '{sym}'")
    except Exception as e:
        print(f"Error for '{sym}': {e}")
