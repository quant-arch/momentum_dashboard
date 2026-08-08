"""
fetch_index_ohlc_truedata.py
=============================
Fetch daily OHLC data for major Nifty indices from TrueData.

Indexes fetched:
  1. Nifty 50                  -> TrueData: "NIFTY 50"
  2. Nifty 500                 -> TrueData: "NIFTY 500"
  3. Nifty Midcap 150          -> TrueData: "NIFTY MIDCAP 150"
  4. Nifty Smallcap 250        -> TrueData: "NIFTY SMLCAP 250"
  5. Nifty 50:25:25 Multi Cap  -> TrueData: "NIFTY MULTI CAP 50:25:25"

Fallback logic:
  - Primary:   fetch enough history to cover 01-01-2014 -> 08-05-2026.
  - Fallback:  if the earliest data point is after 01-01-2016, retry with
               a duration covering 01-01-2016 -> 08-05-2026.
  - Ultimate:  if fallback also fails, accept whatever first data point
               TrueData returns.

Output:
  - One CSV per index saved to Index_OHLC_Data/
  - Columns: Date, Open, High, Low, Close
"""

import os
import sys
import time
import logging
import pandas as pd
from datetime import datetime

# ---------------------------------------------------------------------------
# Ensure truedata_connector (in the same folder) is importable
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from truedata_connector import get_td_obj

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Display name -> TrueData ticker symbol (adjust if your TrueData account
# uses different symbols).
INDEXES = {
    "Nifty_50": "NIFTY 50",
    "Nifty_500": "NIFTY 500",
    "Nifty_Midcap_150": "NIFTY MIDCAP 150",
    # Confirmed TrueData symbol: "NIFTY SMLCAP 250" (not "NIFTY SMALLCAP 250")
    "Nifty_Smallcap_250": "NIFTY SMLCAP 250",
    # Confirmed TrueData symbol: "NIFTY MULTICAP 50:25:25"
    "Nifty_50_25_25_Multi_Cap": "NIFTY500 MULTICAP",
}

# Date boundaries
PRIMARY_START = datetime(2014, 1, 1)
FALLBACK_START = datetime(2016, 1, 1)
END_DATE = datetime(2026, 5, 8)

# Output folder (created automatically)
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "Index_OHLC_Data")

# Fetch tuning
BAR_SIZE = "EOD"
MAX_RETRIES = 3
RETRY_SLEEP = 2.0          # seconds between retries
INDEX_SLEEP = 0.5          # seconds between tickers


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _duration_in_days(start: datetime, end: datetime) -> str:
    """Return a TrueData-style duration string with a 30-day buffer."""
    delta = end - start
    days = max(delta.days + 30, 1)
    return f"{days} D"


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename incoming TrueData columns to a standard lowercase schema."""
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    rename_map = {}
    # Date / timestamp
    for col in ("timestamp", "datetime", "date", "time"):
        if col in df.columns:
            rename_map[col] = "date"
            break

    # OHLC  (short aliases first so we don't overwrite with long ones)
    for src, tgt in (("o", "open"), ("h", "high"), ("l", "low"), ("c", "close"),
                     ("open", "open"), ("high", "high"), ("low", "low"), ("close", "close")):
        if src in df.columns and tgt not in rename_map.values():
            rename_map[src] = tgt

    df = df.rename(columns=rename_map)
    return df


def _fetch_single(
    td_obj,
    ticker: str,
    duration: str,
    bar_size: str = BAR_SIZE,
    max_retries: int = MAX_RETRIES,
) -> pd.DataFrame | None:
    """
    Fetch historic data for *ticker* using the live TrueData object.
    Returns a DataFrame with columns [date, open, high, low, close]
    or None if every attempt fails.
    """
    clean = ticker.replace(".NS", "").strip()

    for attempt in range(1, max_retries + 1):
        try:
            raw = td_obj.get_historic_data([clean], duration=duration, bar_size=bar_size)

            # --- Parse response ------------------------------------------------
            if raw is None:
                logger.warning(f"[{ticker}] Raw response is None (attempt {attempt}/{max_retries})")
                time.sleep(RETRY_SLEEP)
                continue

            if isinstance(raw, list):
                if not raw:
                    logger.warning(f"[{ticker}] Raw response is empty list (attempt {attempt}/{max_retries})")
                    time.sleep(RETRY_SLEEP)
                    continue
                df = pd.DataFrame(raw)
            else:
                df = raw.copy()

            if df.empty:
                logger.warning(f"[{ticker}] Empty DataFrame returned (attempt {attempt}/{max_retries})")
                time.sleep(RETRY_SLEEP)
                continue

            # --- Normalise -----------------------------------------------------
            df = _normalize_columns(df)

            if "date" not in df.columns:
                logger.error(f"[{ticker}] No recognisable date column after normalisation")
                time.sleep(RETRY_SLEEP)
                continue

            df["date"] = pd.to_datetime(df["date"])

            # Keep only the columns we care about
            keep = [c for c in ("date", "open", "high", "low", "close") if c in df.columns]
            df = df[keep].copy()

            if "close" not in df.columns:
                logger.error(f"[{ticker}] Close price missing after normalisation")
                time.sleep(RETRY_SLEEP)
                continue

            logger.info(f"[{ticker}] Fetched {len(df)} rows (attempt {attempt}/{max_retries})")
            return df.sort_values("date").reset_index(drop=True)

        except Exception as exc:
            logger.warning(f"[{ticker}] Attempt {attempt}/{max_retries} raised: {exc}")
            if attempt < max_retries:
                time.sleep(RETRY_SLEEP)
            else:
                logger.error(f"[{ticker}] All {max_retries} attempts exhausted.")
                return None

    return None


def _save_csv(df: pd.DataFrame, display_name: str, out_dir: str) -> str:
    """Write DataFrame to CSV with title-cased columns [Date, Open, High, Low, Close]."""
    os.makedirs(out_dir, exist_ok=True)

    out = df.copy()
    # lowercase -> title case
    out = out.rename(columns={c: c.title() for c in out.columns})

    # Enforce column order
    order = [c for c in ("Date", "Open", "High", "Low", "Close") if c in out.columns]
    out = out[order]

    path = os.path.join(out_dir, f"{display_name}.csv")
    out.to_csv(path, index=False)
    logger.info(f"Saved: {path}  ({len(out)} rows)")
    return path


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("=" * 60)
    logger.info("Index OHLC Fetcher — TrueData")
    logger.info(f"Primary range:    {PRIMARY_START.date()}  ->  {END_DATE.date()}")
    logger.info(f"Fallback range:   {FALLBACK_START.date()}  ->  {END_DATE.date()}")
    logger.info(f"Output directory: {OUTPUT_DIR}")
    logger.info("=" * 60)

    # 1. Connect to TrueData
    try:
        td_obj = get_td_obj()
    except Exception as exc:
        logger.critical(f"Could not connect to TrueData: {exc}")
        return

    primary_dur = _duration_in_days(PRIMARY_START, END_DATE)
    fallback_dur = _duration_in_days(FALLBACK_START, END_DATE)
    logger.info(f"Primary duration:  {primary_dur}")
    logger.info(f"Fallback duration: {fallback_dur}")

    summary: dict[str, int | None] = {}

    for display_name, ticker in INDEXES.items():
        logger.info(f"\n--- {display_name}  ({ticker}) ---")

        # ---- Attempt 1: Primary (target 2014) -----------------------------
        df = _fetch_single(td_obj, ticker, primary_dur, BAR_SIZE)

        use_fallback = False
        if df is not None and not df.empty:
            earliest = df["date"].min()
            logger.info(f"[{ticker}] Earliest data point: {earliest.date()}")
            # If earliest date is *after* the fallback threshold, re-fetch
            if earliest > pd.Timestamp(FALLBACK_START):
                logger.warning(
                    f"[{ticker}] Earliest date {earliest.date()} is later than "
                    f"fallback threshold {FALLBACK_START.date()}. Retrying with fallback duration..."
                )
                use_fallback = True
        else:
            use_fallback = True

        # ---- Attempt 2: Fallback (target 2016) ----------------------------
        if use_fallback:
            df = _fetch_single(td_obj, ticker, fallback_dur, BAR_SIZE)
            if df is not None and not df.empty:
                earliest = df["date"].min()
                logger.info(f"[{ticker}] Fallback earliest data point: {earliest.date()}")

        # ---- Validate -------------------------------------------------------
        if df is None or df.empty:
            logger.error(f"[{ticker}] FAILED — no data retrieved for {display_name}")
            summary[display_name] = None
            continue

        # ---- Trim to requested end date ------------------------------------
        df = df[df["date"] <= pd.Timestamp(END_DATE)].copy()
        if df.empty:
            logger.error(f"[{ticker}] FAILED — no data within requested end date")
            summary[display_name] = None
            continue

        # ---- Save ----------------------------------------------------------
        _save_csv(df, display_name, OUTPUT_DIR)
        summary[display_name] = len(df)

        time.sleep(INDEX_SLEEP)

    # ---- Final summary -----------------------------------------------------
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    for name, count in summary.items():
        status = "✅" if count else "❌"
        rows = f"{count} rows" if count else "FAILED"
        logger.info(f"  {status} {name:<30} {rows}")
    logger.info(f"\nOutput folder: {OUTPUT_DIR}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
