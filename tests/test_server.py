import sys
import csv
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from server import median, parse_ts_ist, load_trips, clean_trips, IST


def test_median_odd():
    assert median([1, 3, 5]) == 3
    assert median([10, 20, 30, 40, 50]) == 30
    assert median([5]) == 5


def test_median_even():
    assert median([1, 2, 3, 4]) == 2.5
    assert median([10, 20, 30, 40]) == 25.0
    assert median([1, 100]) == 50.5


def test_median_unsorted():
    assert median([5, 1, 3, 2, 4]) == 3


def test_parse_ts_ist_valid():
    dt, flags = parse_ts_ist("2026-06-15T09:00:00+05:30")
    assert dt is not None
    assert flags == []


def test_parse_ts_ist_empty():
    dt, flags = parse_ts_ist("")
    assert dt is None
    assert flags == []


def test_parse_ts_ist_invalid_timestamp():
    dt, flags = parse_ts_ist("2026-06-17T08:60:00+05:30")
    assert dt is None
    assert "invalid_timestamp" in flags


def test_parse_ts_ist_wrong_timezone():
    dt, flags = parse_ts_ist("2026-06-16T09:23:00+00:00")
    assert dt is not None
    assert "wrong_timezone" in flags
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 19800  # +05:30


def test_dedup_real_duplicate():
    csv_data = (
        "trip_id,service_date,route_id,route_label,vehicle_plate,device_id,"
        "scheduled_departure,actual_departure,scheduled_arrival,actual_arrival,booked_seats,capacity\n"
        "TRIP_052,2026-06-18,R-09,Route 9,MH-02-3344,D-27,"
        "2026-06-18T18:30:00+05:30,2026-06-18T18:33:00+05:30,"
        "2026-06-18T19:40:00+05:30,2026-06-18T19:49:00+05:30,36,40\n"
        "TRIP_053,2026-06-18,R-09,Route 9,MH-02-3344,D-27,"
        "2026-06-18T18:30:00+05:30,2026-06-18T18:33:00+05:30,"
        "2026-06-18T19:40:00+05:30,2026-06-18T19:49:00+05:30,36,40\n"
    )
    rows = list(csv.DictReader(io.StringIO(csv_data)))
    seen = set()
    deduped = []
    for row in rows:
        key = (
            row["service_date"],
            row["route_id"],
            row["vehicle_plate"],
            row.get("scheduled_departure", ""),
            row.get("actual_departure", ""),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    assert len(deduped) == 1


def test_dedup_near_duplicate():
    csv_data = (
        "trip_id,service_date,route_id,route_label,vehicle_plate,device_id,"
        "scheduled_departure,actual_departure,scheduled_arrival,actual_arrival,booked_seats,capacity\n"
        "TRIP_101,2026-06-15,R-15,Route 15,MH-12-5512,D-18,"
        "2026-06-15T09:00:00+05:30,2026-06-15T09:03:00+05:30,"
        ",2026-06-15T10:15:00+05:30,30,40\n"
        "TRIP_106,2026-06-15,R-15,Route 15,MH-12-5512,D-18,"
        "2026-06-15T09:00:00+05:30,2026-06-15T09:03:00+05:30,"
        "2026-06-15T09:56:00+05:30,2026-06-15T09:53:00+05:30,38,40\n"
    )
    f = io.StringIO(csv_data)
    rows = list(csv.DictReader(f))
    seen = set()
    deduped = []
    for row in rows:
        key = (
            row["service_date"],
            row["route_id"],
            row["vehicle_plate"],
            row.get("scheduled_departure", ""),
            row.get("actual_departure", ""),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    assert len(deduped) == 1


def test_clean_trips_drops_wrong_timezone(tmp_path):
    csv_data = (
        "trip_id,service_date,route_id,route_label,vehicle_plate,device_id,"
        "scheduled_departure,actual_departure,scheduled_arrival,actual_arrival,booked_seats,capacity\n"
        "TRIP_044,2026-06-16,R-09,Route 9,MH-12-3402,D-15,"
        "2026-06-16T08:15:00+05:30,2026-06-16T08:16:00+05:30,"
        "2026-06-16T09:20:00+05:30,2026-06-16T09:23:00+00:00,33,40\n"
    )
    p = tmp_path / "trips.csv"
    p.write_text(csv_data, encoding="utf-8")
    rows = load_trips(p)
    clean, dropped = clean_trips(rows)
    assert len(clean) == 0
    assert any("timezone" in r[1] for r in dropped)


def test_clean_trips_keeps_invalid_timestamp(tmp_path):
    csv_data = (
        "trip_id,service_date,route_id,route_label,vehicle_plate,device_id,"
        "scheduled_departure,actual_departure,scheduled_arrival,actual_arrival,booked_seats,capacity\n"
        "TRIP_031,2026-06-17,R-33,Route 33,MH-14-5590,D-22,"
        "2026-06-17T08:00:00+05:30,2026-06-17T08:60:00+05:30,"
        "2026-06-17T09:05:00+05:30,2026-06-17T09:12:00+05:30,31,40\n"
    )
    p = tmp_path / "trips.csv"
    p.write_text(csv_data, encoding="utf-8")
    rows = load_trips(p)
    clean, dropped = clean_trips(rows)
    assert len(clean) == 1
    assert clean[0]["_departure_delay_min"] is None
