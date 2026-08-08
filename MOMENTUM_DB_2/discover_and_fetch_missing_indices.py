"""
discover_and_fetch_missing_indices.py
======================================
1. Fetch the full symbol list from TrueData.
2. Search that list for symbols matching:
      - Nifty Smallcap 250
      - Nifty 50:25:25 Multi Cap
3. Fetch full OHLC history for the discovered symbols.
4. Save to CSV in Index_OHLC_Data/.
"""

import os
import sys
import time
import logging
import re
import pandas as pd
from datetime import datetime

# Monkey-patch for pandas 3.0 / truedata compatibility
if not hasattr(pd.DataFrame, "timestamp"):
    def _get_df_timestamp(self):
        return self["timestamp"] if "timestamp" in self.columns else None
    def _set_df_timestamp(self, value):
        self["timestamp"] = value
    pd.DataFrame.timestamp = property(_get_df_timestamp, _set_df_timestamp)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj, USERNAME, PASSWORD

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Output folder
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "Index_OHLC_Data")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Date boundaries
PRIMARY_START = datetime(2014, 1, 1)
FALLBACK_START = datetime(2016, 1, 1)
END_DATE = datetime(2026, 5, 8)


def _duration_in_days(start: datetime, end: datetime) -> str:
    delta = end - start
    days = max(delta.days + 30, 1)
    return f"{days} D"


def get_all_symbols(td_obj) -> list[str]:
    """
    Try multiple ways to pull the master symbol list from TrueData.
    Returns a list of symbol strings.
    """
    symbols = []

    # --- Method 1: TD_hist.get_symbols() or similar -----------------------
    for method_name in ("get_symbols", "getSymbols", "get_symbol_list", "symbols", "getAllSymbols"):
        if hasattr(td_obj, method_name):
            try:
                meth = getattr(td_obj, method_name)
                raw = meth()
                if raw is not None:
                    if isinstance(raw, pd.DataFrame):
                        # Try common column names
                        for col in ("symbol", "Symbol", "SYMBOL", "ticker", "Ticker", "TICKER", "name", "Name"):
                            if col in raw.columns:
                                symbols = raw[col].dropna().astype(str).str.strip().tolist()
                                logger.info(f"Method 1 ({method_name}) DataFrame: found {len(symbols)} symbols.")
                                break
                    elif isinstance(raw, list):
                        symbols = [str(s).strip() for s in raw if s]
                        logger.info(f"Method 1 ({method_name}) list: found {len(symbols)} symbols.")
                    elif isinstance(raw, dict):
                        # sometimes symbols are values or keys
                        vals = list(raw.values())
                        if vals and isinstance(vals[0], str):
                            symbols = [str(v).strip() for v in vals]
                        else:
                            symbols = [str(k).strip() for k in raw.keys()]
                        logger.info(f"Method 1 ({method_name}) dict: found {len(symbols)} symbols.")
                    if symbols:
                        return symbols
            except Exception as exc:
                logger.debug(f"Method 1 ({method_name}) failed: {exc}")

    # --- Method 2: REST API endpoints -------------------------------------
    import requests
    endpoints = [
        ("https://api.truedata.in/getAllSymbols", {}),
        ("https://api.truedata.in/getSymbols", {}),
        ("https://api.truedata.in/getAllSymbols", {"user": USERNAME, "password": PASSWORD}),
        ("https://api.truedata.in/getSymbols", {"user": USERNAME, "password": PASSWORD}),
    ]
    for url, params in endpoints:
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    symbols = [str(s).strip() for s in data if s]
                elif isinstance(data, dict):
                    # Try common keys
                    for key in ("symbols", "data", "results", "list", "items"):
                        if key in data and isinstance(data[key], list):
                            symbols = [str(s).strip() for s in data[key] if s]
                            break
                    if not symbols:
                        symbols = [str(k).strip() for k in data.keys()]
                if symbols:
                    logger.info(f"Method 2 ({url}) found {len(symbols)} symbols.")
                    return symbols
        except Exception as exc:
            logger.debug(f"Method 2 ({url}) failed: {exc}")

    # --- Method 3: try get_historic_data with a wildcard / index query -----
    # Some TrueData versions support fetching index lists via special tickers
    try:
        raw = td_obj.get_historic_data(["INDEX"], duration="1 D", bar_size="EOD")
        if raw is not None and hasattr(raw, "empty") and not raw.empty:
            logger.info("Method 3 returned sample data — no master list available this way.")
    except Exception:
        pass

    if not symbols:
        logger.warning("Could not retrieve full symbol list from TrueData via automated methods.")
    return symbols


def search_symbols(symbols: list[str], keywords: list[str]) -> list[str]:
    """Return symbols that contain any of the keywords (case-insensitive)."""
    hits = []
    for sym in symbols:
        sym_upper = sym.upper()
        for kw in keywords:
            if kw.upper() in sym_upper:
                hits.append(sym)
                break
    return sorted(set(hits))


def test_fetch(td_obj, ticker: str, duration: str = "30 D") -> tuple[bool, int | str]:
    """Quick test fetch. Returns (success, row_count_or_error)."""
    try:
        raw = td_obj.get_historic_data([ticker], duration=duration, bar_size="EOD")
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


def fetch_full_history(td_obj, ticker: str, display_name: str) -> pd.DataFrame | None:
    """Fetch full history with fallback start-date logic."""
    primary_dur = _duration_in_days(PRIMARY_START, END_DATE)
    fallback_dur = _duration_in_days(FALLBACK_START, END_DATE)

    # Primary attempt
    df = _fetch_single(td_obj, ticker, primary_dur)
    use_fallback = False
    if df is not None and not df.empty:
        earliest = df["date"].min()
        logger.info(f"[{ticker}] Primary earliest: {earliest.date()}")
        if earliest > pd.Timestamp(FALLBACK_START):
            logger.warning(f"[{ticker}] Earliest {earliest.date()} > fallback threshold. Retrying...")
            use_fallback = True
    else:
        use_fallback = True

    # Fallback attempt
    if use_fallback:
        df = _fetch_single(td_obj, ticker, fallback_dur)
        if df is not None and not df.empty:
            logger.info(f"[{ticker}] Fallback earliest: {df['date'].min().date()}")

    if df is None or df.empty:
        logger.error(f"[{ticker}] No data retrieved.")
        return None

    # Trim to end date
    df = df[df["date"] <= pd.Timestamp(END_DATE)].copy()
    if df.empty:
        logger.error(f"[{ticker}] No data within requested end date.")
        return None

    return df


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    rename_map = {}
    for col in ("timestamp", "datetime", "date", "time"):
        if col in df.columns:
            rename_map[col] = "date"
            break
    for src, tgt in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"),
                     ("open", "open"), ("high", "high"), ("low", "low"), ("close", "close")):
        if src in df.columns and tgt not in rename_map.values():
            rename_map[src] = tgt
    df = df.rename(columns=rename_map)
    return df


def _fetch_single(td_obj, ticker: str, duration: str, max_retries: int = 3) -> pd.DataFrame | None:
    clean = ticker.replace(".NS", "").strip()
    for attempt in range(1, max_retries + 1):
        try:
            raw = td_obj.get_historic_data([clean], duration=duration, bar_size="EOD")
            if raw is None:
                time.sleep(1)
                continue
            if isinstance(raw, list):
                if not raw:
                    time.sleep(1)
                    continue
                df = pd.DataFrame(raw)
            else:
                df = raw.copy() if hasattr(raw, "copy") else raw
            if hasattr(df, "empty") and df.empty:
                time.sleep(1)
                continue
            df = _normalize_columns(df)
            if "date" not in df.columns:
                time.sleep(1)
                continue
            df["date"] = pd.to_datetime(df["date"])
            keep = [c for c in ("date", "open", "high", "low", "close") if c in df.columns]
            df = df[keep].copy()
            if "close" not in df.columns:
                time.sleep(1)
                continue
            return df.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            logger.warning(f"[{ticker}] Attempt {attempt}/{max_retries} failed: {exc}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)
            else:
                return None
    return None


def save_csv(df: pd.DataFrame, display_name: str) -> str:
    out = df.copy()
    out = out.rename(columns={c: c.title() for c in out.columns})
    order = [c for c in ("Date", "Open", "High", "Low", "Close") if c in out.columns]
    out = out[order]
    path = os.path.join(OUTPUT_DIR, f"{display_name}.csv")
    out.to_csv(path, index=False)
    logger.info(f"Saved: {path} ({len(out)} rows)")
    return path


def main():
    logger.info("=" * 60)
    logger.info("Discover & Fetch Missing Index Symbols")
    logger.info("=" * 60)

    # 1. Connect
    try:
        td_obj = get_td_obj()
    except Exception as exc:
        logger.critical(f"Could not connect to TrueData: {exc}")
        return

    # 2. Get all symbols
    logger.info("Fetching full symbol list from TrueData...")
    all_symbols = get_all_symbols(td_obj)
    if not all_symbols:
        logger.error("No symbols retrieved. Cannot proceed with discovery.")
        return
    logger.info(f"Total symbols available: {len(all_symbols)}")

    # 3. Search for our two missing indices
    smallcap_keywords = ["SMALLCAP", "SMALL CAP", "SC 250", "SC250", "SMALLCAP250", "SMALLCAP 250"]
    multicap_keywords = ["MULTI CAP", "MULTICAP", "50:25:25", "502525", "MULTI CAP 50"]

    smallcap_candidates = search_symbols(all_symbols, smallcap_keywords)
    multicap_candidates = search_symbols(all_symbols, multicap_keywords)

    logger.info(f"Smallcap 250 candidates: {smallcap_candidates}")
    logger.info(f"Multi Cap 50:25:25 candidates: {multicap_candidates}")

    # 4. Test candidates
    discovered = {}

    logger.info("\n--- Testing Smallcap 250 candidates ---")
    for sym in smallcap_candidates:
        ok, info = test_fetch(td_obj, sym)
        if ok:
            logger.info(f"  ✅ {sym} -> {info} rows")
            discovered["Nifty_Smallcap_250"] = sym
            break
        else:
            logger.info(f"  ❌ {sym} -> {info}")

    logger.info("\n--- Testing Multi Cap 50:25:25 candidates ---")
    for sym in multicap_candidates:
        ok, info = test_fetch(td_obj, sym)
        if ok:
            logger.info(f"  ✅ {sym} -> {info} rows")
            discovered["Nifty_50_25_25_Multi_Cap"] = sym
            break
        else:
            logger.info(f"  ❌ {sym} -> {info}")

    if not discovered:
        logger.error("No symbols discovered for either index. Exiting.")
        return

    # 5. Fetch full history for discovered symbols
    for display_name, ticker in discovered.items():
        logger.info(f"\n--- Fetching full history: {display_name} ({ticker}) ---")
        df = fetch_full_history(td_obj, ticker, display_name)
        if df is not None:
            save_csv(df, display_name)
        time.sleep(0.5)

    logger.info("\n" + "=" * 60)
    logger.info("Done. Check Index_OHLC_Data/ folder for outputs.")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
