"""Weekly orchestrator for the Moon Event Scout.

Runs on a GitHub Actions schedule (see .github/workflows/weekly-events.yml).
Reads the Config tab, runs the agent to discover + rank events, and writes the
three tabs of the Google Sheet. The Google service-account key stays here on the
runner — it never enters the agent's sandbox.

Required env (GitHub Secrets):
    ANTHROPIC_API_KEY
    AGENT_ID
    ENVIRONMENT_ID
    GOOGLE_SHEET_ID
    GOOGLE_SERVICE_ACCOUNT_JSON   # full service-account key JSON, pasted as a secret
"""
import os
import json
import datetime
import anthropic
import gspread
from google.oauth2.service_account import Credentials

AGENT_ID = os.environ["AGENT_ID"]
ENVIRONMENT_ID = os.environ["ENVIRONMENT_ID"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
SA_INFO = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

# --- Google Sheets (host-side; the key never enters the agent container) ---
gc = gspread.authorize(Credentials.from_service_account_info(
    SA_INFO, scopes=["https://www.googleapis.com/auth/spreadsheets"]))
ss = gc.open_by_key(SHEET_ID)
config_ws = ss.worksheet("Config")
current_ws = ss.worksheet("Current Events")
past_ws = ss.worksheet("Past Events")

COLUMNS = ["name", "date", "time", "location", "source", "url",
           "description", "relevance", "audience_fit", "price"]


def read_config():
    # Config tab columns: Type (keyword|tag|source) | Value
    rows = config_ws.get_all_records()
    keywords = [str(r["Value"]).strip() for r in rows
                if str(r.get("Type", "")).strip().lower() in ("keyword", "tag") and r.get("Value")]
    sources = [str(r["Value"]).strip() for r in rows
               if str(r.get("Type", "")).strip().lower() == "source" and r.get("Value")]
    return keywords, sources


def sheet_text(ws, max_rows=400):
    rows = ws.get_all_values()[:max_rows]
    return "\n".join("\t".join(c for c in row) for row in rows) or "(empty)"


def row_from(e):
    return [e.get("name", ""), e.get("date", ""), e.get("time", ""), e.get("location", ""),
            e.get("source", ""), e.get("url", ""), e.get("description", ""), e.get("relevance", ""),
            "; ".join(e.get("audience_fit") or []), e.get("price", "")]


def write_sheets(payload, run_date):
    top_10 = payload.get("top_10", [])
    current = payload.get("current_events", [])
    archive = payload.get("archive_events", []) or []

    # Current Events tab: Top 10 section, then the full upcoming list
    rows = [[f"TOP 10 MOST PROMISING — week of {run_date}"], COLUMNS]
    rows += [row_from(e) for e in top_10]
    rows += [[], [f"ALL UPCOMING EVENTS ({len(current)})"], COLUMNS]
    rows += [row_from(e) for e in current]
    current_ws.clear()
    current_ws.update(values=rows, range_name="A1")

    # Past Events tab: append the newly-archived events
    if archive:
        if not past_ws.get_all_values():
            past_ws.update(values=[COLUMNS], range_name="A1")
        past_ws.append_rows([row_from(e) for e in archive], value_input_option="RAW")


def build_kickoff(run_date, keywords, sources, current_text, past_text):
    return (
        f"Run date (today): {run_date}\n\n"
        f"Interest keywords/tags to match:\n- " + "\n- ".join(keywords) + "\n\n"
        f"Event sources to scan:\n- " + "\n- ".join(sources) + "\n\n"
        "Existing CURRENT EVENTS already in the sheet (dedupe against these; "
        "anything now before the run date should be archived):\n"
        f"{current_text}\n\n"
        "Existing PAST EVENTS (already archived — do not re-list):\n"
        f"{past_text}\n\n"
        "Find this week's matching upcoming events, dedupe, rank the top 10, and call "
        "submit_events once."
    )


def run_weekly():
    keywords, sources = read_config()
    if not keywords or not sources:
        raise SystemExit("Config tab is missing keywords or sources — check the sheet.")
    run_date = datetime.date.today().isoformat()
    kickoff = build_kickoff(run_date, keywords, sources,
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
