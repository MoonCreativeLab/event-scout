"""One-off: re-apply formatting to the EXISTING Current Events sheet.

No agent run, no cost. Reads creds from .env, converts the Date/Time columns
from text into real date/time values, bolds + tints the title rows, bolds the
header rows, and freezes the top two rows. Mirrors what run_weekly.write_sheets
now does, but against whatever is already in the sheet. Throwaway diagnostic.
"""
import json
import gspread
from google.oauth2.service_account import Credentials

HEADERS = ["Name", "Date", "Time", "Location", "Online/In-person", "Category",
           "Source", "URL", "Description", "Relevance", "Audience Fit", "Price"]
DATE_COL, TIME_COL, LAST_COL = 2, 3, len(HEADERS)


def col_letter(idx):
    return chr(ord("A") + idx - 1)


def env(key):
    with open(".env") as f:
        for line in f:
            line = line.strip()
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} not found in .env")


sa_path = env("GOOGLE_SERVICE_ACCOUNT_FILE")
with open(sa_path) as f:
    sa_info = json.load(f)
gc = gspread.authorize(Credentials.from_service_account_info(
    sa_info, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
ws = gc.open_by_key(env("GOOGLE_SHEET_ID")).worksheet("Current Events")

rows = ws.get_all_values()
n = len(rows)
print(f"Read {n} rows.")

# Locate title rows (section banners) and header rows (the Name/Date/... line).
title_rows, header_rows = [], []
for i, row in enumerate(rows, start=1):
    first = row[0] if row else ""
    if first.startswith("TOP 10 MOST PROMISING") or first.startswith("ALL UPCOMING EVENTS"):
        title_rows.append(i)
    elif row[:len(HEADERS)] == HEADERS:
        header_rows.append(i)
print(f"title rows={title_rows}  header rows={header_rows}")

# 1) Convert Date/Time text -> real values by rewriting those two columns USER_ENTERED.
date, time = col_letter(DATE_COL), col_letter(TIME_COL)
col_b = [[r[DATE_COL - 1] if len(r) >= DATE_COL else ""] for r in rows]
col_c = [[r[TIME_COL - 1] if len(r) >= TIME_COL else ""] for r in rows]
ws.update(values=col_b, range_name=f"{date}1:{date}{n}", value_input_option="USER_ENTERED")
ws.update(values=col_c, range_name=f"{time}1:{time}{n}", value_input_option="USER_ENTERED")
print("Rewrote Date/Time columns as USER_ENTERED.")

# 2) Formatting: bold+tint titles, bold headers, date/time number formats.
last_col = col_letter(LAST_COL)
title_fill = {"red": 0.85, "green": 0.92, "blue": 0.98}
formats = [{"range": f"A{r}:{last_col}{r}",
            "format": {"textFormat": {"bold": True}, "backgroundColor": title_fill}}
           for r in title_rows]
formats += [{"range": f"A{r}:{last_col}{r}", "format": {"textFormat": {"bold": True}}}
            for r in header_rows]
formats += [
    {"range": f"{date}3:{date}{n}",
     "format": {"numberFormat": {"type": "DATE", "pattern": "ddd, mmm d"}}},
    {"range": f"{time}3:{time}{n}",
     "format": {"numberFormat": {"type": "TIME", "pattern": "hh:mm"}}},
]
ws.batch_format(formats)
print(f"Applied {len(formats)} format ranges.")

ws.freeze(rows=2)
print("Froze top 2 rows. Done.")
