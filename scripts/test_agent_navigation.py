#!/usr/bin/env python3
"""
Test aria-navigation-tool directly with a synthetic Seattle incident payload.

Usage:
    python scripts/test_agent_navigation.py
    python scripts/test_agent_navigation.py --trigger crime_keyword_detected
"""
import argparse
import boto3
import json
import sys
import time

REGION = "us-east-1"

PAYLOADS = {
    "location_detected": {
        "incident_id": f"test-nav-{int(time.time())}",
        "context_so_far": "My husband collapsed at 1420 East Pike Street Capitol Hill he's not breathing",
        "trigger_reason": "location_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "medical",
            "location": {"address": "1420 E Pike St, Seattle, WA", "lat": 47.6148, "lng": -122.3130},
        },
        "source": "test",
    },
    "crime_keyword_detected": {
        "incident_id": f"test-nav-crime-{int(time.time())}",
        "context_so_far": "There's a man with a gun on 3rd Avenue downtown Seattle near Pike Street",
        "trigger_reason": "crime_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "crime",
            "location": {"address": "3rd Ave & Pike St, Seattle, WA", "lat": 47.6089, "lng": -122.3388},
        },
        "source": "test",
    },
}


def run_test(trigger: str) -> None:
    payload = PAYLOADS.get(trigger)
    if not payload:
        print(f"Unknown trigger '{trigger}'. Choose: {list(PAYLOADS.keys())}", file=sys.stderr)
        sys.exit(1)

    client = boto3.client("lambda", region_name=REGION)
    incident_id = payload["incident_id"]

    print(f"Testing aria-navigation-tool")
    print(f"  Trigger:     {trigger}")
    print(f"  Incident ID: {incident_id}")
    print(f"  Context:     {payload['context_so_far'][:80]}...")
    print()

    t0 = time.time()
    resp = client.invoke(
        FunctionName="aria-navigation-tool",
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    elapsed = round((time.time() - t0) * 1000)
    result = json.loads(resp["Payload"].read())

    print(f"Elapsed: {elapsed}ms")
    print(f"Status:  {result.get('status')}")
    print()

    units = result.get("recommended_units", [])
    best = result.get("recommended_unit")

    if best:
        print(f"Best unit:  {best.get('unit_id')} ({best.get('unit_type')})")
        print(f"ETA:        {best.get('eta_minutes')} minutes")
        print(f"Route URL:  {best.get('turn_by_turn_url', '')[:80]}")
    else:
        print("WARNING: No recommended unit returned")

    if units:
        print(f"\nTop {len(units)} units:")
        for u in units:
            print(f"  {u.get('unit_id'):10} {u.get('unit_type'):15} ETA: {u.get('eta_minutes')} min")
    else:
        print("WARNING: No units available in aria-units table — run scripts/seed_units.py first")

    print()
    # Validate
    errors = []
    if result.get("status") != "ok":
        errors.append(f"status was '{result.get('status')}', expected 'ok'")
    if not best:
        errors.append("no recommended_unit in response")
    if best and not best.get("eta_minutes"):
        errors.append("eta_minutes missing from recommended_unit")

    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("✓ Navigation agent test passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test aria-navigation-tool Lambda")
    parser.add_argument("--trigger", default="location_detected",
                        choices=list(PAYLOADS.keys()))
    args = parser.parse_args()
    run_test(args.trigger)
