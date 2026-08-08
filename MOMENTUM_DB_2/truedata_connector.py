import os
"""
truedata_connector.py
======================
Shared TrueData connection helper with auto-reconnect on IP/session drops.

Why this exists:
  TrueData sessions can drop if your IP changes (dynamic IP) or if the
  WebSocket times out mid-run. This module wraps init and fetch with:
    1. Auto-reconnect on failure (up to MAX_RETRIES attempts)
    2. Exponential backoff between retries
    3. Session refresh: creates a brand-new TD object on each reconnect,
       which re-authenticates with TrueData and gets a new session token

Usage:
    from truedata_connector import get_td_obj, resilient_fetch

    td = get_td_obj()
    df = resilient_fetch(td, 'RELIANCE', start_date, end_date)
"""

import time
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

USERNAME = os.getenv("TRUEDATA_USERNAME")
PASSWORD = os.getenv("TRUEDATA_PASSWORD")

MAX_RETRIES   = 5     # attempts per fetch
BACKOFF_BASE  = 2.0   # seconds (doubles each retry)
RECONNECT_ON  = (ConnectionError, TimeoutError, OSError)

# Module-level singleton so we don't reconnect unnecessarily
_td_obj = None


def _create_connection():
    """Create a fresh TrueData connection (re-authenticates = new session)."""
    # Try truedata (history API) first
    try:
        from truedata import TD_hist as TD
        obj = TD(USERNAME, PASSWORD)
        logger.info("Connected via truedata.TD_hist")
        return obj
    except Exception:
        pass

    # Fallback: truedata_ws WebSocket API
    try:
        from truedata_ws.websocket.TD import TD
        obj = TD(USERNAME, PASSWORD, live_port=None)
        logger.info("Connected via truedata_ws.TD")
        return obj
    except Exception as e:
        raise RuntimeError(f"Could not connect to TrueData with either library: {e}")


def get_td_obj(force_reconnect=False):
    """
    Return a live TrueData object.
    Creates a new connection if none exists or if force_reconnect=True.
    """
    global _td_obj
    if _td_obj is None or force_reconnect:
        print("Connecting to TrueData...")
        _td_obj = _create_connection()
        print("Connected.\n")
    return _td_obj


def resilient_fetch(td_obj, ticker, start_date, end_date, max_retries=MAX_RETRIES):
    """
    Fetch historical OHLC data with automatic reconnect on session/IP drops.

    Returns a normalised DataFrame with columns: date, open, high, low, close
    Returns None if all retries fail.
    """
    global _td_obj
    clean = ticker.replace('.NS', '')
    days_back = (datetime.now() - start_date).days + 30
    duration_str = f"{days_back} D"

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            raw = td_obj.get_historic_data([clean], duration=duration_str, bar_size='EOD')

            if raw is None:
                return None
            if isinstance(raw, list):
                if not raw:
                    return None
                df = pd.DataFrame(raw)
            else:
                df = raw.copy()

            if df.empty:
                return None

            # --- Normalise columns ---
            df.columns = [c.lower() for c in df.columns]
            rename = {}
            for col in ['timestamp', 'datetime', 'date', 'time']:
                if col in df.columns:
                    rename[col] = 'date'
                    break
            for src, tgt in [('o','open'),('h','high'),('l','low'),('c','close')]:
                if src in df.columns:
                    rename[src] = tgt
            df.rename(columns=rename, inplace=True)

            if 'date' not in df.columns:
                return None

            df['date'] = pd.to_datetime(df['date'])

            # Filter to requested date range
            mask = (df['date'] >= pd.Timestamp(start_date)) & \
                   (df['date'] <= pd.Timestamp(end_date))
            df = df.loc[mask].copy()

            return df if not df.empty else None

        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            is_conn_issue = any(k in err_str for k in [
                'connection', 'timeout', 'reset', 'broken pipe',
                'eof', 'socket', 'ip', 'auth', 'session', 'disconnect'
            ])

            if is_conn_issue or attempt < max_retries:
                wait = BACKOFF_BASE ** attempt
                print(f"\n  [{ticker}] Attempt {attempt}/{max_retries} failed: {e}")
                print(f"  Reconnecting in {wait:.0f}s...")
                time.sleep(wait)
                try:
                    # Force a brand-new connection (new session = new IP handshake)
                    _td_obj = _create_connection()
                    td_obj = _td_obj
                except Exception as conn_err:
                    print(f"  Reconnect failed: {conn_err}")
            else:
                break

    logger.error(f"All {max_retries} attempts failed for {ticker}: {last_exc}")
    return None
