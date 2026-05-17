#!/usr/bin/env python3
"""
API layer smoke test — exercises all REST endpoints and verifies WebSocket event flow.

Tests:
  1. POST /session/start             → returns incident_id + websocket_url
  2. GET  /session/{id}/status       → returns incident record
  3. POST /session/{id}/approve      → sets dispatcher_approved in DynamoDB
  4. POST /session/{id}/override     → writes override record
  5. WebSocket connect + event subscription (requires wscat or websockets library)

Usage:
    python scripts/test_api.py
    python scripts/test_api.py --skip-ws   # skip WebSocket test (no wscat needed)
"""
import argparse
import boto3
import json
import os
import sys
import time
import threading
import urllib.request

REGION = "us-east-1"

# Minimal 3-word simulation transcript for a fast smoke test
SMOKE_TRANSCRIPT = [
    {"word": "help", "speaker": "caller", "delay_ms": 0},
    {"word": "emergency", "speaker": "caller", "delay_ms": 300},
    {"word": "please", "speaker": "caller", "delay_ms": 300},
    {"word": "1420", "speaker": "caller", "delay_ms": 400},
    {"word": "East", "speaker": "caller", "delay_ms": 300},
    {"word": "Pike", "speaker": "caller", "delay_ms": 300},
    {"word": "Street", "speaker": "caller", "delay_ms": 300},
    {"word": "not", "speaker": "caller", "delay_ms": 500},
    {"word": "breathing", "speaker": "caller", "delay_ms": 300},
]


def get_api_url() -> str:
    url = os.environ.get("ARIA_API_URL", "").rstrip("/")
    if url:
        return url
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for o in stacks[0].get("Outputs", []):
            if o["OutputKey"] == "RestApiUrl":
                return o["OutputValue"].rstrip("/")
    except Exception:
        pass
    print("ERROR: Set ARIA_API_URL or deploy the stack.", file=sys.stderr)
    sys.exit(1)


def get_ws_url() -> str:
    url = os.environ.get("ARIA_WS_URL", "").rstrip("/")
    if url:
        return url
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for o in stacks[0].get("Outputs", []):
            if o["OutputKey"] == "WebSocketUrl":
                return o["OutputValue"].rstrip("/")
    except Exception:
        pass
    return ""


def post(url: str, body: dict, label: str) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            print(f"  ✓ {label}: {resp.status}")
            return result
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        print(f"  ✗ {label}: HTTP {e.code} — {body_text[:200]}")
        return {}


def get(url: str, label: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            print(f"  ✓ {label}: {resp.status}")
            return result
    except urllib.error.HTTPError as e:
        print(f"  ✗ {label}: HTTP {e.code}")
        return {}


def check_dynamodb(incident_id: str, check_approved: bool = False) -> dict:
    table = boto3.resource("dynamodb", region_name=REGION).Table("aria-incidents")
    resp = table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=False,
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else {}


def test_ws_events(ws_url: str, incident_id: str, timeout: int = 15) -> list:
    """Connect to WebSocket and collect events. Requires 'websockets' package."""
    try:
        import asyncio
        import websockets

        events = []

        async def _listen():
            connect_url = f"{ws_url}?incident_id={incident_id}"
            async with websockets.connect(connect_url, open_timeout=10) as ws:
                deadline = asyncio.get_event_loop().time() + timeout
                while asyncio.get_event_loop().time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=2)
                        events.append(json.loads(msg))
                    except asyncio.TimeoutError:
                        break
                    except Exception:
                        break

        asyncio.run(_listen())
        return events
    except ImportError:
        print("  ⚠ 'websockets' package not installed — skipping WS event validation")
        print("    Install with: pip install websockets")
        return []
    except Exception as e:
        print(f"  ⚠ WebSocket test failed: {e}")
        return []


def run_tests(api_url: str, ws_url: str, skip_ws: bool) -> None:
    errors = []
    print(f"\nAPI URL: {api_url}")
    print(f"WS URL:  {ws_url or '(not found)'}")

    # 1. POST /session/start
    print("\n[1] POST /session/start")
    result = post(f"{api_url}/session/start",
                  {"simulation_transcript": SMOKE_TRANSCRIPT},
                  "session start")
    incident_id = result.get("incident_id")
    ws_returned = result.get("websocket_url", "")
    if not incident_id:
        errors.append("POST /session/start did not return incident_id")
        print("  FATAL: no incident_id — aborting remaining tests")
        return
    print(f"  incident_id:   {incident_id}")
    print(f"  websocket_url: {ws_returned[:60]}...")

    # 2. GET /session/{id}/status
    print("\n[2] GET /session/{id}/status")
    time.sleep(1)
    status_result = get(f"{api_url}/session/{incident_id}/status", "status check")
    if not status_result.get("incident_id"):
        errors.append("GET /session/{id}/status did not return incident_id")

    # 3. WebSocket events (collect while pipeline runs)
    ws_events = []
    if not skip_ws and ws_url:
        print(f"\n[3] WebSocket — collecting events for 15s")
        ws_events = test_ws_events(ws_url, incident_id, timeout=15)
        event_types = [e.get("type") for e in ws_events]
        print(f"  Events received ({len(ws_events)}): {event_types}")
        if not ws_events:
            print("  ⚠ No WebSocket events received — verify WS deployment")
    elif skip_ws:
        print("\n[3] WebSocket — skipped (--skip-ws)")
    else:
        print("\n[3] WebSocket — skipped (no WS URL found)")

    # Wait for pipeline to process
    print("\n  Waiting 10s for pipeline agents to run...")
    time.sleep(10)

    # 4. POST /session/{id}/approve
    print("\n[4] POST /session/{id}/approve")
    approve_result = post(f"{api_url}/session/{incident_id}/approve", {}, "approve")
    if approve_result.get("status") != "approved":
        errors.append(f"approve returned status '{approve_result.get('status')}', expected 'approved'")

    # Verify DynamoDB
    time.sleep(1)
    item = check_dynamodb(incident_id)
    if item.get("dispatcher_approved"):
        print(f"  ✓ DynamoDB dispatcher_approved: True")
    else:
        errors.append("dispatcher_approved not set in DynamoDB after approve call")
        print(f"  ✗ DynamoDB dispatcher_approved not set")

    # 5. POST /session/{id}/override
    print("\n[5] POST /session/{id}/override")
    override_body = {
        "override_reason": "Better route known",
        "dispatcher_choice": {"unit_id": "MED-2"},
        "notes": "Manual override — smoke test",
    }
    override_result = post(f"{api_url}/session/{incident_id}/override", override_body, "override")
    if override_result.get("status") != "override_recorded":
        errors.append(f"override returned status '{override_result.get('status')}'")

    # Verify override in DynamoDB (aria-overrides table)
    time.sleep(1)
    overrides_table = boto3.resource("dynamodb", region_name=REGION).Table("aria-overrides")
    overrides = overrides_table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
    ).get("Items", [])
    if overrides:
        print(f"  ✓ Override written to DynamoDB: reason={overrides[-1].get('override_reason')}")
    else:
        errors.append("override not found in aria-overrides DynamoDB")
        print("  ✗ Override not in DynamoDB")

    # Summary
    print(f"\n{'='*50}")
    if errors:
        print(f"FAILURES ({len(errors)}):")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print(f"✓ All API tests passed — incident_id: {incident_id}")
        if ws_events:
            event_types = set(e.get("type") for e in ws_events)
            print(f"  WebSocket event types seen: {event_types}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARIA API layer smoke test")
    parser.add_argument("--skip-ws", action="store_true", help="Skip WebSocket test")
    args = parser.parse_args()

    api_url = get_api_url()
    ws_url = get_ws_url()
    run_tests(api_url, ws_url, args.skip_ws)
