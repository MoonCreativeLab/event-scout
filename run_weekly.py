"""Weekly orchestrator for the Moon Event Scout.

Runs on a GitHub Actions schedule (see .github/workflows/weekly-events.yml).
Reads the Config tab, runs the agent to discover + rank events, and writes the
three tabs of the Google Sheet. The Google service-account key stays here on the
runner — it never enters the agent's sandbox.

Required env:
    ANTHROPIC_API_KEY
    AGENT_ID
    ENVIRONMENT_ID
    GOOGLE_SHEET_ID
    Google service-account credentials — provide ONE of:
      GOOGLE_SERVICE_ACCOUNT_JSON   # full key JSON inline (used in CI / GitHub Secrets)
      GOOGLE_SERVICE_ACCOUNT_FILE   # path to the key file (convenient for local runs)
"""
import os
import json
import datetime
import anthropic
import gspread
from google.oauth2.service_account import Credentials


def load_service_account_info():
    """Service-account creds from inline JSON (CI) or a file path (local)."""
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if raw:
        return json.loads(raw)
    path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    if path:
        with open(os.path.expanduser(path)) as f:
            return json.load(f)
    raise SystemExit(
        "Set GOOGLE_SERVICE_ACCOUNT_JSON (inline, for CI) or "
        "GOOGLE_SERVICE_ACCOUNT_FILE (path to the key file, for local runs)."
    )


AGENT_ID = os.environ["AGENT_ID"]
ENVIRONMENT_ID = os.environ["ENVIRONMENT_ID"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
SA_INFO = load_service_account_info()

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

# --- Google Sheets (host-side; the key never enters the agent container) ---
gc = gspread.authorize(Credentials.from_service_account_info(
    SA_INFO, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
ss = gc.open_by_key(SHEET_ID)
config_ws = ss.worksheet("Config")
current_ws = ss.worksheet("Current Events")
past_ws = ss.worksheet("Past Events")

# Event columns as (machine key, display header). The key matches what the agent
# submits via submit_events; the header is the human-friendly label written to the sheet.
FIELDS = [
    ("name", "Name"),
    ("date", "Date"),
    ("time", "Time"),
    ("location", "Location"),
    ("format", "Online/In-person"),
    ("category", "Category"),
    ("source", "Source"),
    ("url", "URL"),
    ("description", "Description"),
    ("relevance", "Relevance"),
    ("audience_fit", "Audience Fit"),
    ("price", "Price"),
]
HEADERS = [header for _, header in FIELDS]

# 1-based column positions, derived from FIELDS so they stay in sync with the layout.
KEYS = [key for key, _ in FIELDS]
DATE_COL = KEYS.index("date") + 1
TIME_COL = KEYS.index("time") + 1
LAST_COL = len(FIELDS)


def col_letter(idx):  # 1-based -> A, B, C ... (fine for our <=26 columns)
    return chr(ord("A") + idx - 1)


def read_config():
    # Config tab: column A = Type (keyword|tag|source|location), column B = Value.
    # Read ONLY columns A:B (from row 2, skipping the header) so anything parked
    # in later columns — the Instructions box, notes, stray cells — is ignored.
    # This sidesteps get_all_records()'s duplicate-header check entirely.
    rows = config_ws.get("A2:B")  # list of [type, value]; trailing blanks trimmed

    def values_for(*types):
        out = []
        for r in rows:
            typ = (r[0] if len(r) > 0 else "").strip().lower()
            val = (r[1] if len(r) > 1 else "").strip()
            if typ in types and val:
                out.append(val)
        return out

    keywords = values_for("keyword", "tag")
    sources = values_for("source")
    locations = values_for("location")
    return keywords, sources, locations


def sheet_text(ws, max_rows=400):
    rows = ws.get_all_values()[:max_rows]
    return "\n".join("\t".join(c for c in row) for row in rows) or "(empty)"


def row_from(e):
    row = []
    for key, _ in FIELDS:
        val = e.get(key, "")
        if isinstance(val, list):  # e.g. audience_fit, or a multi-topic category
            val = "; ".join(str(v) for v in val)
        row.append(val)
    return row


def date_time_formats(last_row, first_row=2):
    """Number-format specs for the Date/Time columns over a row range."""
    date = col_letter(DATE_COL)
    time = col_letter(TIME_COL)
    return [
        {"range": f"{date}{first_row}:{date}{last_row}",
         "format": {"numberFormat": {"type": "DATE", "pattern": "ddd, mmm d"}}},
        {"range": f"{time}{first_row}:{time}{last_row}",
         "format": {"numberFormat": {"type": "TIME", "pattern": "hh:mm"}}},
    ]


def write_sheets(payload, run_date):
    top_10 = payload.get("top_10", [])
    current = payload.get("current_events", [])
    archive = payload.get("archive_events", []) or []

    # Current Events tab: Top 10 section, then the full upcoming list
    rows = [[f"TOP 10 MOST PROMISING — week of {run_date}"], HEADERS]
    rows += [row_from(e) for e in top_10]
    rows += [[], [f"ALL UPCOMING EVENTS ({len(current)})"], HEADERS]
    rows += [row_from(e) for e in current]
    current_ws.clear()
    current_ws.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")

    # Bold both section titles and both header rows; tint the title rows;
    # format Date/Time columns; freeze the top title+header rows.
    # Row layout: 1=title, 2=headers, then top_10, blank, ALL-UPCOMING title, headers.
    last_col = col_letter(LAST_COL)
    title_rows = [1, 4 + len(top_10)]
    header_rows = [2, 5 + len(top_10)]
    title_fill = {"red": 0.85, "green": 0.92, "blue": 0.98}  # light blue
    formats = [{"range": f"A{r}:{last_col}{r}",
                "format": {"textFormat": {"bold": True}, "backgroundColor": title_fill}}
               for r in title_rows]
    formats += [{"range": f"A{r}:{last_col}{r}", "format": {"textFormat": {"bold": True}}}
                for r in header_rows]
    formats += date_time_formats(len(rows), first_row=3)
    current_ws.batch_format(formats)
    current_ws.freeze(rows=2)  # keep the title + first header row visible while scrolling

    # Past Events tab: append the newly-archived events
    if archive:
        if not past_ws.get_all_values():
            past_ws.update(values=[HEADERS], range_name="A1")
            past_ws.batch_format([{"range": f"A1:{col_letter(LAST_COL)}1",
                                   "format": {"textFormat": {"bold": True}}}])
            past_ws.freeze(rows=1)
        past_ws.append_rows([row_from(e) for e in archive],
                            value_input_option="USER_ENTERED")
        past_ws.batch_format(date_time_formats(len(past_ws.get_all_values())))


def build_kickoff(run_date, keywords, sources, locations, current_text, past_text):
    location_block = (
        f"Priority locations (favor in-person events in/near these; great virtual events are "
        f"welcome too):\n- " + "\n- ".join(locations) + "\n\n"
        if locations else ""
    )
    return (
        f"Run date (today): {run_date}\n\n"
        f"Interest keywords/tags to match:\n- " + "\n- ".join(keywords) + "\n\n"
        f"Event sources to scan:\n- " + "\n- ".join(sources) + "\n\n"
        + location_block +
        "Existing CURRENT EVENTS already in the sheet (dedupe against these; "
        "anything now before the run date should be archived):\n"
        f"{current_text}\n\n"
        "Existing PAST EVENTS (already archived — do not re-list):\n"
        f"{past_text}\n\n"
        "Find this week's matching upcoming events, dedupe, rank the top 10, and call "
        "submit_events once."
    )


def run_weekly():
    keywords, sources, locations = read_config()
    if not keywords or not sources:
        raise SystemExit("Config tab is missing keywords or sources — check the sheet.")
    run_date = datetime.date.today().isoformat()
    kickoff = build_kickoff(run_date, keywords, sources, locations,
                            sheet_text(current_ws), sheet_text(past_ws))

    session = client.beta.sessions.create(
        agent=AGENT_ID,  # latest version; pin with {"type": "agent", "id": ..., "version": ...}
        environment_id=ENVIRONMENT_ID,
        title=f"Moon event scout — {run_date}",
    )
    print(f"Watch in Console: "
          f"https://platform.claude.com/workspaces/default/sessions/{session.id}")

    sent = submitted = False
    while True:
        # NOTE: re-opening the stream each turn can miss events emitted during the gap.
        # Fine for a batch job; for hardening, consolidate via events.list() on reconnect
        # (managed-agents-client-patterns Pattern 1).
        with client.beta.sessions.events.stream(session_id=session.id) as stream:
            if not sent:
                client.beta.sessions.events.send(
                    session_id=session.id,
                    events=[{"type": "user.message",
                             "content": [{"type": "text", "text": kickoff}]}],
                )
                sent = True
            pending, terminal = [], False
            for event in stream:
                if event.type == "agent.message":
                    for b in event.content:
                        if b.type == "text":
                            print(b.text, end="", flush=True)
                elif event.type == "agent.custom_tool_use":
                    pending.append(event)
                elif event.type == "session.status_idle":
                    if getattr(getattr(event, "stop_reason", None), "type", None) == "requires_action":
                        break  # there are tool calls to answer
                    terminal = True
                    break
                elif event.type == "session.status_terminated":
                    terminal = True
                    break

        if pending:
            results = []
            for call in pending:
                if call.name == "submit_events":
                    write_sheets(call.input, run_date)
                    submitted = True
                    results.append({"type": "user.custom_tool_result",
                                    "custom_tool_use_id": call.id,
                                    "content": [{"type": "text",
                                                 "text": "Saved. Current Events and Past Events tabs updated."}]})
                else:
                    results.append({"type": "user.custom_tool_result",
                                    "custom_tool_use_id": call.id, "is_error": True,
                                    "content": [{"type": "text", "text": f"Unknown tool {call.name}"}]})
            client.beta.sessions.events.send(session_id=session.id, events=results)
            continue
        if terminal:
            break

    if not submitted:
        raise SystemExit("Agent finished without calling submit_events — check the session in Console.")


if __name__ == "__main__":
    run_weekly()
