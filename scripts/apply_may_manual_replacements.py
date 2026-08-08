"""
Apply manual May-2026 replacements after outputs are generated.
Replaces ADANIENSOL -> VEDL for May 2026 rows in master and per-window result files.
Creates backups before modifying files.
Usage: python scripts/apply_may_manual_replacements.py
"""
from pathlib import Path
import shutil
import pandas as pd
import sys

ROOT = Path(__file__).resolve().parents[1]
STOCKS_DIR = ROOT / "Stocks"
MASTER_PATHS = [
    STOCKS_DIR / "ticker_master_may26_20_stocks_results" / "master_momentum_summary.xlsx",
    STOCKS_DIR / "Nifty_500_2025_Apr_20_stocks_results" / "master_momentum_summary.xlsx",
]
REPLACE_FROM = "ADANIENSOL"
REPLACE_TO = "VEDL"
REPLACE_ISIN = "INE205A01025"  # chosen canonical ISIN


def backup_file(p: Path):
    bak = p.with_name(p.stem + "_backup_before_manual_replace" + p.suffix)
    shutil.copy(p, bak)
    return bak


def try_read_excel(p: Path):
    try:
        return pd.read_excel(p)
    except Exception:
        return None


def try_read_csv(p: Path):
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def replace_in_dataframe(df: pd.DataFrame, path: Path) -> int:
    changed = 0
    # find ticker-like column
    ticker_cols = [c for c in df.columns if c.strip().upper() in ("TICKER", "SYMBOL")]
    date_cols = [c for c in df.columns if c.strip().upper() in ("END_DATE", "DATE")]
    if not ticker_cols:
        # try heuristic: any column named like 'Ticker' substring
        for c in df.columns:
            if 'TICKER' in c.strip().upper() or 'SYMBOL' in c.strip().upper():
                ticker_cols.append(c)
    if not ticker_cols:
        return 0
    ticker_col = ticker_cols[0]
    # normalize
    df[ticker_col] = df[ticker_col].astype(str).str.strip().str.upper()

    # build mask for May 2026 if date column present
    if date_cols:
        date_col = date_cols[0]
        try:
            ed = pd.to_datetime(df[date_col], errors='coerce')
            mask_date = (ed.dt.year == 2026) & (ed.dt.month == 5)
        except Exception:
            mask_date = pd.Series([True] * len(df))
    else:
        mask_date = pd.Series([True] * len(df))

    mask = mask_date & (df[ticker_col] == REPLACE_FROM)
    if mask.any():
        # set ticker
        df.loc[mask, ticker_col] = REPLACE_TO
        # set ISIN if present
        isin_cols = [c for c in df.columns if c.strip().upper() in ('ISIN','ISIN CODE','ISIN_CODE')]
        if isin_cols:
            df.loc[mask, isin_cols[0]] = REPLACE_ISIN
        changed = mask.sum()
    return int(changed)


def process_file(p: Path):
    changed = 0
    if p.suffix.lower() in ('.xlsx', '.xls'):
        df = try_read_excel(p)
        if df is None:
            return 0
        bak = backup_file(p)
        changed = replace_in_dataframe(df, p)
        if changed:
            df.to_excel(p, index=False)
    elif p.suffix.lower() == '.csv':
        df = try_read_csv(p)
        if df is None:
            return 0
        bak = backup_file(p)
        changed = replace_in_dataframe(df, p)
        if changed:
            df.to_csv(p, index=False)
    return changed


def main():
    total_changed = 0
    # process master first
    master_found = False
    for mp in MASTER_PATHS:
        if mp.exists():
            master_found = True
            print(f"Processing master: {mp}")
            cnt = process_file(mp)
            print(f"Modified {cnt} rows in master")
            total_changed += cnt
            break
    if not master_found:
        print("No master file found at expected locations.")

    # process per-window files under Stocks (only modify files in Stocks/**/ that look like momentum_*.xlsx or any xlsx/csv)
    for p in STOCKS_DIR.rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.xlsx', '.xls', '.csv'):
            # limit to typical result folders to be safe
            if 'results' in str(p).lower() or 'momentum_' in p.name.lower() or 'master_momentum_summary' in p.name.lower():
                try:
                    cnt = process_file(p)
                except Exception as e:
                    print(f"Error processing {p}: {e}")
                    cnt = 0
                if cnt:
                    print(f"Modified {cnt} rows in {p}")
                total_changed += cnt

    print(f"Done. Total rows modified: {total_changed}")


if __name__ == '__main__':
    main()
