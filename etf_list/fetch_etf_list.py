import csv
import os
import datetime
import requests
import pandas as pd
from io import StringIO

USERNAME = os.getenv("TRUEDATA_USERNAME")
PASSWORD = os.getenv("TRUEDATA_PASSWORD")

OUTPUT_DIR = r"C:\Users\anike\Desktop\Ocean_dev\Momentum Handover\Momentum Handover\etf_list"
os.makedirs(OUTPUT_DIR, exist_ok=True)

today_str = datetime.date.today().strftime("%Y-%m-%d")
OUTPUT_XLSX = os.path.join(OUTPUT_DIR, "etf_list_" + today_str + ".xlsx")
OUTPUT_TXT  = os.path.join(OUTPUT_DIR, "etf_symbols_" + today_str + ".txt")


def normalize_columns(df):
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

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

    for candidate in ("companyname", "company_name", "etfname", "etf_name",
                      "longname", "name", "schemename", "description", "underlying"):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "ETF_Name"
            break

    for candidate in ("isin",):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "ISIN"
            break

    for candidate in ("date", "asofdate", "as_of_date"):
        if candidate in cols_lower:
            col_map[cols_lower[candidate]] = "Date"
            break

    df = df.rename(columns=col_map)

    for col in df.columns:
        if pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].fillna("").astype(str).str.strip()

    preferred_order = [col for col in ("SymbolID", "Symbol", "ETF_Name", "ISIN", "Date") if col in df.columns]
    remaining = [col for col in df.columns if col not in preferred_order]
    return df[preferred_order + remaining]


def parse_truedata_csv(raw_text):
    rows = []
    reader = csv.reader(StringIO(raw_text))

    for row in reader:
        cleaned_row = [cell.strip() for cell in row]
        if any(cleaned_row):
            rows.append(cleaned_row)

    if not rows:
        raise ValueError("TrueData ETF response is empty.")

    header = rows[0]
    data_rows = rows[1:]

    if not data_rows:
        return normalize_columns(pd.DataFrame(columns=header))

    max_columns = max(len(row) for row in data_rows)
    if len(header) < max_columns:
        extra_columns = ["Date"] if max_columns == len(header) + 1 else [f"Extra_{index}" for index in range(1, max_columns - len(header) + 1)]
        header = header + extra_columns

    normalized_rows = []
    for row in data_rows:
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        elif len(row) > len(header):
            row = row[:len(header)]
        normalized_rows.append(row)

    return normalize_columns(pd.DataFrame(normalized_rows, columns=header))

if __name__ == "__main__":
    print("=" * 60)
    print("  TrueData - ETF List Fetcher | Date: " + today_str)
    print("=" * 60)

    # Call getETFlist - returns CSV with user/password as query params
    etf_url = "https://api.truedata.in/getETFlist"
    params = {"date": today_str, "user": USERNAME, "password": PASSWORD}

    print("[INFO] Calling: " + etf_url)
    resp = requests.get(etf_url, params=params, timeout=30)
    print("[INFO] HTTP Status: " + str(resp.status_code))
    resp.raise_for_status()

    # Parse CSV response. TrueData currently returns 4 header labels but 5 data fields.
    df = parse_truedata_csv(resp.text)
    print("[INFO] Rows fetched: " + str(len(df)))
    print("[INFO] Columns: " + str(list(df.columns)))
    print(df.head(10).to_string(index=False))

    # Save Excel
    with pd.ExcelWriter(OUTPUT_XLSX, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="ETF_List")
        ws = writer.sheets["ETF_List"]
        for col_cells in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 60)

    print("\nExcel saved -> " + OUTPUT_XLSX)

    # Save TXT (one symbol per line)
    if "Symbol" in df.columns:
        symbols = df["Symbol"].dropna().astype(str).str.strip().tolist()
        with open(OUTPUT_TXT, "w") as f:
            f.write("\n".join(symbols))
        print("TXT saved   -> " + OUTPUT_TXT + "  (" + str(len(symbols)) + " symbols)")

    print("\nDone.")