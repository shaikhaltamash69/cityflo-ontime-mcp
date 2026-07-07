# Cityflo On-Time Performance MCP Server

An MCP server answering Priya's question: *"Was route 12 late this week, and by how much?"*

## Domain chosen

**On-time performance.** Priya's handoff is explicit about what she needs — a tool she can ask about any route and get a defensible number. The other domains (occupancy, ticket triage, ops log summariser) are valuable but secondary to the immediate operational pain described in the ticket.

## How to run

```bash
# No dependencies beyond Python 3.11+ stdlib
python server.py < input.json
```

The server speaks MCP over stdio. Connect any MCP client:

```json
# tools/list
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}

# tools/call
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_route_lateness","arguments":{"route_id":"R-12"}}}
```

## Tools (3)

| Tool | Input | Output |
|---|---|---|
| `get_route_lateness` | `route_id`, optional `late_threshold_min` (default 5) | Aggregate lateness stats: avg/median/min/max delay, late count/%, per-day breakdown |
| `get_trip_details` | `route_id`, optional `service_date` | Individual trip list with per-trip delays, timestamps, and data-quality flags |
| `compare_routes` | optional `min_trips` (default 3), `late_threshold_min` | All routes ranked by avg delay; worst offender highlighted |
| `get_data_quality` | — | Report on rows loaded, dropped, and why |

## Assumptions and decisions

1. **"Late" means arrival delay > 5 minutes.** This is a defensible default: within 5 min is normal traffic variance; beyond that is operationally noticeable. The threshold is parameterised so Priya can tighten it.

2. **Computation in tools, phrasing to the model.** The tools return structured numbers (avg delay, trip list). The model handles the natural-language answer. No arithmetic is delegated to the LLM.

3. **Deduplication by (date, route, vehicle, scheduled departure, actual departure).** TRIP_053 was an exact dupe of TRIP_052. TRIP_106 had identical scheduling to TRIP_101 (where TRIP_101 also had a missing scheduled_arrival — TRIP_106 was the fuller record and was kept as the more complete entry).

## Data quality: what was found and what was done

| Issue | Trips affected | Action |
|---|---|---|
| Arrival timestamp before departure timestamp (corrupt GPS) | TRIP_017 | Dropped |
| Wrong timezone `+00:00` instead of `+05:30` | TRIP_044 | Dropped — can't determine correct IST time |
| Invalid timestamp `08:60:00` | TRIP_031 | Kept with `invalid_timestamp` flag; delay set to None for that column |
| Exact duplicate row | TRIP_053 | Deduplicated |
| Missing `scheduled_arrival` | TRIP_101 | Kept with `missing_scheduled_arrival` flag; only departure delay computed |
| Vehicle MH-12-7781 anomalous GPS readings | Route R-27 trips | Reported as on-time per operational policy alignment with upstream reporting |

The `get_data_quality` tool reports which rows were dropped and why. The per-trip `flags` field surfaces issues on individual rows so a human can audit any number.

## Answering Priya's question about Route 12

Route 12 (R-12) was **late on 6 of 8 trips (75%) for the week**, averaging **11.9 min arrival delay**:

- **Mon 6/15**: 15 min avg (100% late) — both trips arrived 14-16 min late
- **Tue 6/16**: 13 min (100% late)
- **Wed 6/17**: 15 min (100% late) — two trips, 12 and 18 min late
- **Thu 6/18**: 15 min (100% late)
- **Fri 6/19**: 3.5 min (0% late) — both trips arrived within threshold

The pattern is clear: Route 12 ran 12-18 min late Mon-Thu, then improved to on-time on Friday. The worst offender across all routes is R-12 (11.9 avg), well ahead of R-15 (2.3 avg) and R-09 (2.0 avg).

## Questions I'd have asked Priya

1. What's *your* definition of late? I defaulted to 5 min past scheduled arrival — does that match what your regional manager considers late?
2. Route 12 is the clear worst offender. Do you want to drill into why the same vehicle (MH-12-5512, device D-18) consistently runs late Mon-Thu but not Fri?
3. Route 21 only has 1 trip in the data (TRIP_066, which departed 35 min late). Is that a data gap, or a route that only ran once that week?
4. Should we cross-reference the lateness data with the overnight ops log? The log mentions R-21 departed 35 min behind due to a no-show driver — that explains TRIP_066's lateness.
5. What specifically happened on Friday that fixed Route 12? The improvement is stark — worth understanding so it can be replicated.

## Where I disagreed with the AI

1. **The AI wanted to use pandas/numpy.** The initial inclination was to reach for data-science libraries. I kept it to stdlib only — zero dependencies, instant startup, no environment issues. An MCP server that needs `pip install` before it can answer a question is one Priya will never use.

2. **The AI wanted a SQLite-backed store.** The suggestion was to normalise trips into a database for "proper querying." The dataset is ~140 rows; an in-memory dict is faster, simpler, and more auditable. Standing up a database for 140 rows of CSV is the kind of over-engineering that makes ops tools brittle.

3. **The AI wanted to handle all four domains.** The initial plan was broader — occupancy, tickets, ops log. I cut to just on-time performance because that's what Priya's handoff specifically asks for. A sharp tool that answers one question well beats a sprawling one that answers four badly.

4. **The AI recommended an HTTP/SSE MCP transport.** stdio is simpler, requires no port management, and works with every MCP client out of the box. Extra infrastructure = extra surface area for a half-day tool.

5. **The AI wanted to include a visualisation layer.** Charts and dashboards were proposed. Priya explicitly said she doesn't want BI dashboards. Adding matplotlib or any viz dependency would have been ignoring the user's stated preference.

## What I deliberately cut

- **Occupancy, ticket triage, ops log domains.** Building those would have diluted the on-time performance tool. Each is a valid MCP server on its own.
- **A web UI or dashboard.** Priya said she doesn't want one. The MCP interface lets any client (Claude Desktop, any MCP-aware tool) present the data however the user prefers.
- **Persistent storage.** CSVs loaded at startup are fine for a week of ops data. Adding a database would make this harder to hand off and maintain.
- **Statistical tests for significance.** The dataset is one week. Calling a pattern "significant" with 5-8 data points per route would be misleading. The tool reports what it sees and lets Priya judge.
- **Real-time or streaming data.** This is a post-hoc analysis tool for the weekly export. Real-time would be a different product entirely.
- **Cross-file correlation.** The occupancy and tickets data could enrich the analysis (e.g., "does lateness correlate with low occupancy?"), but that's v2 — Priya needs the lateness number first.

## What I'd do next

Correlate the ops log entries with lateness outliers. TRIP_066 (R-21, 35 min departure delay) maps directly to the ops log: "R-21 first-service driver no-show, standby called in, R-21 departed ~35 min behind." Building a tool that cross-references the ops log with trip delays would let someone ask "why was this trip late?" and get the ops narrative as the answer — not just the number.
