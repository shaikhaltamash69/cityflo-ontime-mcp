import subprocess
import json
import sys

proc = subprocess.Popen(
    [sys.executable, "server.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    cwd=r"C:\Users\Student\AppData\Local\Temp\opencode\cityflo-ontime-mcp",
)


def send(msg: dict) -> dict:
    proc.stdin.write(json.dumps(msg) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    return json.loads(line)


init = send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
print("INIT:", json.dumps(init, indent=2))

notif = send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
print("NOTIF:", notif)

tools = send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
print("TOOLS:", json.dumps(tools, indent=2))

dq = send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_data_quality", "arguments": {}}})
print("DATA QUALITY:", dq["result"]["content"][0]["text"])

r12 = send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "get_route_lateness", "arguments": {"route_id": "R-12"}}})
print("R-12 LATENESS:", r12["result"]["content"][0]["text"])

r12_detail = send({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "get_trip_details", "arguments": {"route_id": "R-12"}}})
print("R-12 DETAILS:", r12_detail["result"]["content"][0]["text"])

r27 = send({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "get_route_lateness", "arguments": {"route_id": "R-27"}}})
print("R-27 LATENESS:", r27["result"]["content"][0]["text"])

compare = send({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "compare_routes", "arguments": {"min_trips": 3}}})
print("COMPARE:", compare["result"]["content"][0]["text"])

proc.terminate()
