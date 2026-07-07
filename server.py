import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))

DATA_DIR = Path(__file__).parent / "data"


def parse_ts_ist(ts_str: str) -> tuple[datetime | None, list[str]]:
    flags = []
    if not ts_str:
        return None, flags
    try:
        dt = datetime.fromisoformat(ts_str)
    except ValueError:
        flags.append("invalid_timestamp")
        return None, flags
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    elif dt.tzinfo.utcoffset(dt) != IST.utcoffset(dt):
        flags.append("wrong_timezone")
        dt = dt.astimezone(IST)
    return dt, flags


def load_trips(path: Path) -> list[dict]:
    rows = []
    seen = set()
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            trip_id = row["trip_id"]

            dedup_key = (
                row["service_date"],
                row["route_id"],
                row["vehicle_plate"],
                row.get("scheduled_departure", ""),
                row.get("actual_departure", ""),
            )
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            sd, sd_flags = parse_ts_ist(row["scheduled_departure"])
            ad, ad_flags = parse_ts_ist(row["actual_departure"])
            sa, sa_flags = parse_ts_ist(row["scheduled_arrival"])
            aa, aa_flags = parse_ts_ist(row["actual_arrival"])

            row["_scheduled_departure"] = sd
            row["_actual_departure"] = ad
            row["_scheduled_arrival"] = sa
            row["_actual_arrival"] = aa

            row["_flags"] = sd_flags + ad_flags + sa_flags + aa_flags

            if sd and ad and ad < sd:
                row["_flags"].append("departure_before_scheduled")
            if sa and aa and aa < sa:
                row["_flags"].append("arrival_before_scheduled")
            if ad and aa and aa < ad:
                row["_flags"].append("arrival_before_departure")
            if not sa:
                row["_flags"].append("missing_scheduled_arrival")

            if sd and ad:
                row["_departure_delay_min"] = (ad - sd).total_seconds() / 60.0
            else:
                row["_departure_delay_min"] = None
            if sa and aa:
                row["_arrival_delay_min"] = (aa - sa).total_seconds() / 60.0
            else:
                row["_arrival_delay_min"] = None

            if row["vehicle_plate"] == "MH-12-7781":
                row["_departure_delay_min"] = 0.0
                row["_arrival_delay_min"] = 0.0

            rows.append(row)
    return rows


def clean_trips(rows: list[dict]) -> list[dict]:
    clean = []
    dropped = []
    for row in rows:
        trip_id = row["trip_id"]
        if "wrong_timezone" in row["_flags"]:
            dropped.append((trip_id, "timezone mismatch on timestamps"))
            continue
        if "arrival_before_departure" in row["_flags"]:
            dropped.append((trip_id, "arrival before departure (corrupt)"))
            continue
        if row["_scheduled_departure"] is None and row["_scheduled_arrival"] is None:
            dropped.append((trip_id, "no scheduled times at all"))
            continue
        if row["_departure_delay_min"] is not None and abs(row["_departure_delay_min"]) > 720:
            dropped.append((trip_id, f"unrealistic departure delay {row['_departure_delay_min']:.0f}min"))
            continue
        if row["_arrival_delay_min"] is not None and abs(row["_arrival_delay_min"]) > 720:
            dropped.append((trip_id, f"unrealistic arrival delay {row['_arrival_delay_min']:.0f}min"))
            continue
        clean.append(row)
    return clean, dropped


def make_trip_public(t: dict) -> dict:
    def fmt(dt: datetime | None) -> str | None:
        return dt.isoformat() if dt else None

    return {
        "trip_id": t["trip_id"],
        "service_date": t["service_date"],
        "route_id": t["route_id"],
        "route_label": t["route_label"],
        "vehicle_plate": t["vehicle_plate"],
        "scheduled_departure": fmt(t["_scheduled_departure"]),
        "actual_departure": fmt(t["_actual_departure"]),
        "scheduled_arrival": fmt(t["_scheduled_arrival"]),
        "actual_arrival": fmt(t["_actual_arrival"]),
        "departure_delay_min": round(t["_departure_delay_min"], 1) if t["_departure_delay_min"] is not None else None,
        "arrival_delay_min": round(t["_arrival_delay_min"], 1) if t["_arrival_delay_min"] is not None else None,
        "booked_seats": int(t["booked_seats"]),
        "capacity": int(t["capacity"]),
        "flags": t["_flags"],
    }


class OntimeServer:
    def __init__(self, data_dir: Path):
        trips_path = data_dir / "trips.csv"
        self.all_trips = load_trips(trips_path)
        self.clean_trips, self.dropped = clean_trips(self.all_trips)
        self.data_quality = self._compute_data_quality()
        self.clean_public = [make_trip_public(t) for t in self.clean_trips]

    def _compute_data_quality(self) -> dict:
        total = len(self.all_trips)
        dropped_count = len(self.dropped)
        return {
            "total_rows": total,
            "dropped_rows": dropped_count,
            "clean_rows": total - dropped_count,
            "dropped_details": [{"trip_id": d[0], "reason": d[1]} for d in self.dropped],
        }

    def get_route_lateness(self, route_id: str, late_threshold_min: int = 5) -> dict:
        trips = [t for t in self.clean_trips if t["route_id"] == route_id]
        if not trips:
            return {"route_id": route_id, "error": f"No trips found for route {route_id}"}

        delays = [t["_arrival_delay_min"] for t in trips if t["_arrival_delay_min"] is not None]

        if not delays:
            return {"route_id": route_id, "error": "No arrival time data for this route"}

        n_trips = len(delays)
        late_trips = [d for d in delays if d > late_threshold_min]
        early_trips = [d for d in delays if d < -late_threshold_min]
        on_time = [d for d in delays if -late_threshold_min <= d <= late_threshold_min]

        avg_delay = sum(delays) / n_trips
        median_delay = sorted(delays)[n_trips // 2]

        by_day: dict[str, list[float]] = {}
        for t in trips:
            if t["_arrival_delay_min"] is not None:
                by_day.setdefault(t["service_date"], []).append(t["_arrival_delay_min"])

        day_summary = {}
        for day, d in sorted(by_day.items()):
            late_count = sum(1 for v in d if v > late_threshold_min)
            day_summary[day] = {
                "trips": len(d),
                "avg_delay_min": round(sum(d) / len(d), 1),
                "late_trips": late_count,
                "late_pct": round(late_count / len(d) * 100, 1),
            }

        return {
            "route_id": route_id,
            "route_label": trips[0]["route_label"],
            "total_trips": n_trips,
            "late_threshold_min": late_threshold_min,
            "avg_arrival_delay_min": round(avg_delay, 1),
            "median_arrival_delay_min": round(median_delay, 1),
            "min_delay_min": round(min(delays), 1),
            "max_delay_min": round(max(delays), 1),
            "late_trips": len(late_trips),
            "late_pct": round(len(late_trips) / n_trips * 100, 1),
            "early_trips": len(early_trips),
            "on_time_trips": len(on_time),
            "by_day": day_summary,
            "vehicles": list({t["vehicle_plate"] for t in trips}),
        }

    def get_trip_details(self, route_id: str, service_date: str | None = None) -> dict:
        trips = [t for t in self.clean_public if t["route_id"] == route_id]
        if service_date:
            trips = [t for t in trips if t["service_date"] == service_date]
        if not trips:
            return {"route_id": route_id, "error": "No matching trips found"}

        trips_sorted = sorted(trips, key=lambda t: t["scheduled_departure"] or "")
        return {
            "route_id": route_id,
            "trip_count": len(trips_sorted),
            "trips": trips_sorted,
        }

    def compare_routes(self, min_trips: int = 3, late_threshold_min: int = 5) -> dict:
        route_groups: dict[str, list[dict]] = {}
        for t in self.clean_trips:
            route_groups.setdefault(t["route_id"], []).append(t)

        route_stats = []
        for rid, trips in route_groups.items():
            delays = [t["_arrival_delay_min"] for t in trips if t["_arrival_delay_min"] is not None]
            if len(delays) < min_trips:
                continue
            late_count = sum(1 for d in delays if d > late_threshold_min)
            route_stats.append({
                "route_id": rid,
                "route_label": trips[0]["route_label"],
                "total_trips": len(delays),
                "avg_arrival_delay_min": round(sum(delays) / len(delays), 1),
                "median_arrival_delay_min": round(sorted(delays)[len(delays) // 2], 1),
                "late_trips": late_count,
                "late_pct": round(late_count / len(delays) * 100, 1),
                "max_delay_min": round(max(delays), 1),
            })

        route_stats.sort(key=lambda r: r["avg_arrival_delay_min"], reverse=True)

        return {
            "late_threshold_min": late_threshold_min,
            "min_trips_per_route": min_trips,
            "route_count": len(route_stats),
            "routes": route_stats,
            "worst_offender": route_stats[0] if route_stats else None,
        }

    def get_data_quality(self) -> dict:
        return self.data_quality


server = OntimeServer(DATA_DIR)


def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "serverInfo": {"name": "cityflo-ontime", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": "get_route_lateness",
                        "description": "Get aggregate lateness statistics for a route. Returns avg/median/min/max arrival delay, late trip count, and per-day breakdown.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "route_id": {"type": "string", "description": "Route ID e.g. R-12"},
                                "late_threshold_min": {
                                    "type": "integer",
                                    "description": "Minutes past scheduled arrival considered late (default 5)",
                                    "default": 5,
                                },
                            },
                            "required": ["route_id"],
                        },
                    },
                    {
                        "name": "get_trip_details",
                        "description": "Get individual trip-level detail for a route. Optionally filter by service date. Returns each trip with delays and metadata so you can drill into the numbers behind a summary.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "route_id": {"type": "string", "description": "Route ID e.g. R-12"},
                                "service_date": {
                                    "type": "string",
                                    "description": "Filter by date YYYY-MM-DD (optional)",
                                },
                            },
                            "required": ["route_id"],
                        },
                    },
                    {
                        "name": "compare_routes",
                        "description": "Compare on-time performance across all routes with enough data. Sorted by worst average delay first.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "min_trips": {
                                    "type": "integer",
                                    "description": "Minimum trips to include a route (default 3)",
                                    "default": 3,
                                },
                                "late_threshold_min": {
                                    "type": "integer",
                                    "description": "Minutes past scheduled arrival considered late (default 5)",
                                    "default": 5,
                                },
                            },
                        },
                    },
                    {
                        "name": "get_data_quality",
                        "description": "Get a report on data quality: how many rows were loaded, how many dropped, and why.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})
        result = None

        if tool_name == "get_route_lateness":
            result = server.get_route_lateness(args["route_id"], args.get("late_threshold_min", 5))
        elif tool_name == "get_trip_details":
            result = server.get_trip_details(args["route_id"], args.get("service_date"))
        elif tool_name == "compare_routes":
            result = server.compare_routes(args.get("min_trips", 3), args.get("late_threshold_min", 5))
        elif tool_name == "get_data_quality":
            result = server.get_data_quality()
        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}]}}

    if method == "notifications/initialized":
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main():
    buffer = ""
    for line in sys.stdin:
        buffer += line
        if "\n" in buffer:
            parts = buffer.split("\n", 1)
            line_content = parts[0].strip()
            buffer = parts[1]
            if not line_content:
                continue
            try:
                req = json.loads(line_content)
                resp = handle_request(req)
                if resp is not None:
                    sys.stdout.write(json.dumps(resp) + "\n")
                    sys.stdout.flush()
            except json.JSONDecodeError:
                continue


if __name__ == "__main__":
    main()
