import argparse
import difflib
from pathlib import Path

import pandas as pd


ETF_DIR = Path(__file__).resolve().parent
ROOT_DIR = ETF_DIR.parents[1]
DEFAULT_REFERENCE_FILES = [
    ROOT_DIR / "Indexes" / "etf_symbols_truedata_20260227.csv",
    ROOT_DIR / "Indexes" / "etf_symbols_normalized.csv",
]


def standardize_dataframe(df):
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    if {"Symbolid", "Symbol", "ETF_Name", "ISIN"}.issubset(df.columns):
        symbolid_numeric_ratio = pd.to_numeric(df["Symbolid"], errors="coerce").notna().mean()
        isin_date_ratio = pd.to_datetime(df["ISIN"], errors="coerce").notna().mean()
        if symbolid_numeric_ratio < 0.1 and isin_date_ratio > 0.9:
            df = df.rename(columns={
                "Symbolid": "Symbol",
                "Symbol": "ETF_Name",
                "ETF_Name": "ISIN",
                "ISIN": "Date",
            })

    col_map = {}
    cols_lower = {col.lower().strip(): col for col in df.columns}

    for candidate in ("symbolid", "symbol_id", "symbol id", "id"):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "SymbolID"
            break

    for candidate in ("symbol", "tradingsymbol", "ticker", "scrip"):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "Symbol"
            break

    for candidate in ("companyname", "company_name", "etfname", "etf_name", "underlying", "name"):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "ETF_Name"
            break

    for candidate in ("isin",):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "ISIN"
            break

    for candidate in ("date",):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "Date"
            break

    df = df.rename(columns=col_map)

    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].fillna("").astype(str).str.strip()

    preferred = [col for col in ("SymbolID", "Symbol", "ETF_Name", "ISIN", "Date") if col in df.columns]
    remainder = [col for col in df.columns if col not in preferred]
    return df[preferred + remainder]


def latest_fetch_file():
    candidates = sorted(ETF_DIR.glob("etf_list_*.xlsx"))
    if not candidates:
        raise FileNotFoundError("No etf_list_*.xlsx files found in etf_list directory.")
    return candidates[-1]


def load_fetched_etfs(path):
    df = pd.read_excel(path, dtype=str)
    return standardize_dataframe(df)


def load_reference_tables(paths):
    frames = []
    for path in paths:
        df = pd.read_csv(path, dtype=str)
        df = standardize_dataframe(df)
        df["SourceFile"] = path.name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def best_reference_matches(target_isin, reference_df, limit=5):
    target_isin = target_isin.strip().upper()
    unique_refs = reference_df.drop_duplicates(subset=["ISIN"]).copy()
    unique_refs["ISIN"] = unique_refs["ISIN"].astype(str).str.upper().str.strip()

    prefix_matches = unique_refs[unique_refs["ISIN"].str.startswith(target_isin[:7], na=False)].copy()
    pool = prefix_matches if not prefix_matches.empty else unique_refs

    pool["score"] = pool["ISIN"].map(lambda value: difflib.SequenceMatcher(a=target_isin, b=value).ratio())
    pool = pool.sort_values(["score", "ISIN"], ascending=[False, True])
    return pool[["ISIN", "Symbol", "ETF_Name", "SourceFile", "score"]].head(limit)


def print_rows(label, df):
    print(label)
    if df.empty:
        print("  none")
        return

    columns = [col for col in ("SymbolID", "Symbol", "ETF_Name", "ISIN", "Date", "SourceFile") if col in df.columns]
    print(df[columns].to_string(index=False))


def audit_single_isin(target_isin, fetched_df, reference_df):
    target_isin = target_isin.strip().upper()
    fetched_matches = fetched_df[fetched_df["ISIN"].astype(str).str.upper() == target_isin] if "ISIN" in fetched_df.columns else fetched_df.iloc[0:0]
    reference_matches = reference_df[reference_df["ISIN"].astype(str).str.upper() == target_isin] if "ISIN" in reference_df.columns else reference_df.iloc[0:0]

    print(f"ISIN audit: {target_isin}")
    print_rows("\nIn fetched ETF file:", fetched_matches)
    print_rows("\nIn reference mapping files:", reference_matches)

    if reference_matches.empty:
        print("\nClosest known reference matches:")
        print(best_reference_matches(target_isin, reference_df).to_string(index=False))


def audit_missing_isins(fetched_df, reference_df):
    if "ISIN" not in fetched_df.columns:
        raise KeyError("Fetched ETF file does not contain an ISIN column.")

    fetched_unique = fetched_df.drop_duplicates(subset=["ISIN"]).copy()
    fetched_unique["ISIN"] = fetched_unique["ISIN"].astype(str).str.upper().str.strip()

    reference_isins = set(reference_df["ISIN"].astype(str).str.upper().str.strip())
    missing = fetched_unique[~fetched_unique["ISIN"].isin(reference_isins)].copy()

    print(f"Missing ISIN count: {len(missing)}")
    if missing.empty:
        print("All fetched ISINs are present in the reference mapping files.")
        return

    for _, row in missing.iterrows():
        print("-" * 80)
        print(row[[col for col in ("Symbol", "ETF_Name", "ISIN", "Date") if col in row.index]].to_string())
        print("Closest known reference matches:")
        print(best_reference_matches(row["ISIN"], reference_df, limit=3).to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description="Audit fetched ETF ISINs against local mapping files.")
    parser.add_argument("--isin", help="Audit a specific ISIN instead of the full missing list.")
    parser.add_argument("--fetched-file", help="Path to an ETF workbook generated by fetch_etf_list.py.")
    parser.add_argument("--reference-file", action="append", help="Optional additional/override reference CSV path. Can be provided multiple times.")
    args = parser.parse_args()

    fetched_file = Path(args.fetched_file) if args.fetched_file else latest_fetch_file()
    reference_files = [Path(path) for path in args.reference_file] if args.reference_file else DEFAULT_REFERENCE_FILES

    fetched_df = load_fetched_etfs(fetched_file)
    reference_df = load_reference_tables(reference_files)

    print(f"Fetched ETF file: {fetched_file}")
    print("Reference files:")
    for path in reference_files:
        print(f"  - {path}")

    if args.isin:
        audit_single_isin(args.isin, fetched_df, reference_df)
    else:
        audit_missing_isins(fetched_df, reference_df)


if __name__ == "__main__":
    main()