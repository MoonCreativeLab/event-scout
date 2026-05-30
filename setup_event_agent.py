"""One-time setup for the Moon Event Scout managed agent.

Run this LOCALLY once:

    export ANTHROPIC_API_KEY=sk-ant-...
    python setup_event_agent.py

Copy the printed AGENT_ID and ENVIRONMENT_ID into your GitHub repo Secrets.
Re-running creates NEW agent/environment objects — do NOT run it on the weekly job.
"""
import anthropic

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env

# 1. Environment — cloud sandbox with open web egress (event discovery is open-ended)
environment = client.beta.environments.create(
    name="moon-event-agent-env",
    config={"type": "cloud", "networking": {"type": "unrestricted"}},
)

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "date": {"type": "string", "description": "Start date, ISO 8601 (YYYY-MM-DD)"},
        "time": {"type": "string", "description": "Local start time if known, else empty"},
        "location": {"type": "string", "description": "Venue / city, or 'Virtual'"},
        "source": {"type": "string", "description": "e.g. Eventbrite, Luma, Stanford, Berkeley"},
        "url": {"type": "string"},
        "description": {"type": "string", "description": "1-2 sentence summary"},
        "relevance": {"type": "string", "description": "Why it matters for Moon"},
        "audience_fit": {
            "type": "array",
            "items": {"type": "string",
                      "enum": ["Designer", "Engineer", "Business Developer", "C-Suite"]},
        },
        "price": {"type": "string"},
    },
    "required": ["name", "date", "source", "url"],
}

SYSTEM = """You are the Moon Event Scout for Moon Creative Lab, an enterprise accelerator and \
venture studio in Palo Alto. Each week you discover upcoming tech, startup, and innovation-\
community events and produce a curated report that helps Moon's team — Designers, Engineers, \
Business Developers, and C-Suite leaders — get plugged into promising startups, technology, \
and communities.

## Each run
1. Using web_search and web_fetch, scan the event sources listed in the run message (e.g. \
Eventbrite, Luma, Stanford events, UC Berkeley events) plus any extra sources provided. Search \
aggressively and follow listing pages through to individual event pages — do NOT answer from \
prior knowledge. When current information would change the answer, search before answering.
2. Find UPCOMING events (date on or after the run date given in the message) that match the \
interest keywords/categories/tags provided.
3. Favor SF Bay Area / Peninsula events and high-quality virtual ones; favor startups, emerging \
tech, founders, design, engineering, and enterprise innovation.
4. For each event capture: name, date (ISO YYYY-MM-DD), time, location, source, url, a 1-2 \
sentence description, why it's relevant to Moon, which audience(s) it best fits, and price.
5. De-duplicate against the existing "Current Events" and "Past Events" rows included in the \
run message (match on name + date + source, allowing minor wording differences). Merge your new \
finds with the still-upcoming existing events into one clean list.
6. Archive: any existing Current event whose date is before the run date goes into \
archive_events.
7. Rank the 10 most promising upcoming events as top_10 (best first), weighing relevance to \
Moon's focus, event quality/prestige, networking value, and breadth of audience fit.

## Finishing
Call `submit_events` exactly once with top_10, current_events (the full deduped upcoming list, \
including the top 10), and archive_events. Do not try to write to any sheet yourself — \
submitting the tool is how the report is saved. After it returns successfully, you are done.

Be thorough on discovery: better to surface a borderline event for a human to filter than to \
miss a great one."""

# 2. Agent — full prebuilt toolset + the host-handled submit tool
agent = client.beta.agents.create(
    name="Moon Event Scout",
    model="claude-opus-4-8",
    system=SYSTEM,
    tools=[
        {"type": "agent_toolset_20260401"},  # bash, read, write, edit, glob, grep, web_fetch, web_search
        {
            "type": "custom",
            "name": "submit_events",
            "description": (
                "Submit the finished weekly report. Call exactly once at the end with the full "
                "deduplicated upcoming list, the ranked top 10, and any now-past events to archive."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "top_10": {"type": "array", "items": EVENT_SCHEMA,
                               "description": "10 most promising upcoming events, best first"},
                    "current_events": {"type": "array", "items": EVENT_SCHEMA,
                                       "description": "ALL relevant upcoming events (deduped), incl. top 10"},
                    "archive_events": {"type": "array", "items": EVENT_SCHEMA,
                                       "description": "Existing Current events now in the past"},
                },
                "required": ["top_10", "current_events"],
            },
        },
    ],
)

print("Save these as GitHub Secrets:")
print(f"  AGENT_ID={agent.id}")
print(f"  ENVIRONMENT_ID={environment.id}")
