# Moon Event Scout

A weekly [Managed Agent](https://platform.claude.com/docs/en/managed-agents/overview)
that discovers upcoming tech / startup / innovation-community events (Eventbrite, Luma,
Stanford, Berkeley, and any sources you add), filters them to Moon Creative Lab's interest
areas, and writes a curated report into a Google Sheet — with a **Top 10 most promising**
section and a full upcoming list, plus an archive of past events.

Built for Moon Creative Lab (enterprise accelerator, Palo Alto). The audience spans
Designers, Engineers, Business Developers, and C-Suite.

## How it works

```
GitHub Action (weekly cron)
   └─ run_weekly.py  (orchestrator — holds Google + Anthropic creds)
        ├─ reads the Config tab  → keywords/tags + sources
        ├─ reads Current/Past tabs → context for dedupe + archiving
        ├─ runs the managed agent → web_search/web_fetch discovery + ranking
        │     agent calls submit_events(top_10, current_events, archive_events)
        └─ writes the 3 tabs of the Google Sheet
```

The Google service-account key lives only on the GitHub Actions runner — it is **never**
passed into the agent's sandbox. The agent submits its findings via the `submit_events`
custom tool; the orchestrator does the actual sheet write.

## The Google Sheet (the control panel + output)

One spreadsheet, three tabs. The marketing/comms owner edits only the **Config** tab.

| Tab | Owner | Contents |
|---|---|---|
| `Config` | comms | Two columns: `Type` (`keyword` / `tag` / `source`) and `Value`. One row per entry. |
| `Current Events` | agent | Top 10 section at the top, full upcoming list below. Rewritten each run. |
| `Past Events` | agent | Archive of events whose date has passed. Appended to each run. |

**Example `Config` tab:**

| Type | Value |
|---|---|
| keyword | AI agents |
| keyword | enterprise software |
| tag | founders |
| source | Eventbrite |
| source | Luma |
| source | https://events.stanford.edu |

## Setup (one time)

1. **Create the agent + environment.**
   ```sh
   export ANTHROPIC_API_KEY=sk-ant-...
   pip install -r requirements.txt
   python setup_event_agent.py     # prints AGENT_ID and ENVIRONMENT_ID
   ```
2. **Create a Google service account** (Google Cloud Console → enable the *Google Sheets API*
   → IAM & Admin → Service Accounts → create → add a JSON key). The key's `client_email` is
   the **service-account email**.
3. **Create the Sheet** with the three tabs above, then **Share it (Editor) with the
   service-account email** — otherwise every write 403s.
4. **Add repo Secrets** (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY`
   - `AGENT_ID` and `ENVIRONMENT_ID` (from step 1)
   - `GOOGLE_SHEET_ID` (the long id in the sheet URL)
   - `GOOGLE_SERVICE_ACCOUNT_JSON` (paste the entire key JSON)
5. **Smoke-test:** Actions → *Weekly Moon Event Scout* → **Run workflow**. Open the Console
   link the run prints and confirm the three tabs populate before trusting the Monday cron.

## Triggering

- **Weekly:** cron in `.github/workflows/weekly-events.yml` (Mondays ~7am PT).
- **Manual:** the **Run workflow** button (`workflow_dispatch`).
- **HTTP POST:** uncomment `repository_dispatch` in the workflow, then
  `POST /repos/<owner>/<repo>/dispatches` with `{"event_type":"run-event-scout"}`.

## Notes

- The agent is referenced by **latest version**. To pin for reproducibility, store the
  version and pass `agent={"type": "agent", "id": AGENT_ID, "version": N}` in `run_weekly.py`.
- Some event sites throttle automated fetches; the agent leans on web search to find listings.
  Comms can add direct listing URLs as `source` rows to improve coverage.
- To change the agent's behavior, edit `setup_event_agent.py` and re-run it as an **update**
  (`client.beta.agents.update(...)`) rather than creating a new agent.
