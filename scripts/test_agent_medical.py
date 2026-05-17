#!/usr/bin/env python3
"""
Test aria-medical-tool directly with synthetic Seattle incident payloads.

Usage:
    python scripts/test_agent_medical.py
    python scripts/test_agent_medical.py --scenario overdose
"""
import argparse
import boto3
import json
import sys
import time

REGION = "us-east-1"

SCENARIOS = {
    "cardiac": {
        "incident_id": f"test-med-cardiac-{int(time.time())}",
        "context_so_far": (
            "My husband collapsed at 1420 East Pike Street Capitol Hill "
            "he's not breathing he's unresponsive I think it's a heart attack"
        ),
        "trigger_reason": "medical_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "medical",
            "severity": "critical",
            "location": {"address": "1420 E Pike St, Seattle, WA", "lat": 47.6148, "lng": -122.3130},
            "resources_needed": ["trauma_bay", "cardiac_cath"],
        },
    },
    "overdose": {
        "incident_id": f"test-med-od-{int(time.time())}",
        "context_so_far": (
            "There's a man collapsed on 3rd Avenue downtown he's not breathing "
            "I think he overdosed he's blue"
        ),
        "trigger_reason": "medical_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "medical",
            "severity": "critical",
            "location": {"address": "3rd Ave & Pike, Seattle, WA", "lat": 47.6089, "lng": -122.3388},
            "resources_needed": ["trauma_bay"],
        },
    },
    "trauma": {
        "incident_id": f"test-med-trauma-{int(time.time())}",
        "context_so_far": (
            "There's been a stabbing on First Avenue South SoDo "
            "the victim is bleeding heavily from the chest"
        ),
        "trigger_reason": "medical_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "medical",
            "severity": "critical",
            "location": {"address": "1st Ave S, Seattle, WA 98134", "lat": 47.5951, "lng": -122.3313},
            "resources_needed": ["trauma_bay"],
        },
    },
}


def run_test(scenario_name: str) -> None:
    payload = SCENARIOS.get(scenario_name)
    if not payload:
        print(f"Unknown scenario '{scenario_name}'. Choose: {list(SCENARIOS.keys())}", file=sys.stderr)
        sys.exit(1)

    client = boto3.client("lambda", region_name=REGION)
    incident_id = payload["incident_id"]

    print(f"Testing aria-medical-tool — scenario: {scenario_name}")
    print(f"  Incident ID: {incident_id}")
    print(f"  Context:     {payload['context_so_far'][:80]}...")
    print()

    t0 = time.time()
    resp = client.invoke(
        FunctionName="aria-medical-tool",
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    elapsed = round((time.time() - t0) * 1000)
    result = json.loads(resp["Payload"].read())

    print(f"Elapsed: {elapsed}ms")
    print(f"Status:  {result.get('status')}")
    print()

    hospital = result.get("recommended_hospital", {})
    pre_alert = result.get("pre_alert_status", {})
    triage = result.get("triage_protocol", "")
    source = result.get("source_document", "")

    print(f"Recommended hospital: {hospital.get('name', 'N/A')}")
    print(f"  Hospital ID:  {hospital.get('hospital_id', 'N/A')}")
    print(f"  ETA:          {hospital.get('eta_minutes', 'N/A')} minutes")
    print(f"  ER status:    {hospital.get('er_status', 'N/A')}")
    print()
    print(f"Pre-alert status: {pre_alert.get('status', 'N/A')}")
    print(f"  Hospital name: {pre_alert.get('hospital_name', 'N/A')}")
    print(f"  Notes:         {pre_alert.get('notes', 'N/A')}")
    print()
    print(f"Triage protocol ({source}):")
    print(f"  {triage[:200]}...")

    # Validate
    errors = []
    if result.get("status") != "ok":
        errors.append(f"status was '{result.get('status')}', expected 'ok'")
    if not hospital.get("hospital_id"):
        errors.append("no recommended_hospital — run scripts/seed_units.py first")
    if not hospital.get("name"):
        errors.append("hospital name missing")
    if not pre_alert.get("status"):
        errors.append("no pre_alert_status returned")
    if not triage:
        errors.append("no triage_protocol returned")

    print()
    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("✓ Medical agent test passed")
        print(f"  Hospital: {hospital.get('name')} — ETA {hospital.get('eta_minutes')} min")
        print(f"  Pre-alert: {pre_alert.get('status')}")
        if source and source not in ("fallback", "default-sop"):
            print(f"  KB source: {source} ✓")
        else:
            print(f"  KB source: fallback (KB not yet synced — expected before deployment)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test aria-medical-tool Lambda")
    parser.add_argument("--scenario", default="cardiac", choices=list(SCENARIOS.keys()))
    args = parser.parse_args()
    run_test(args.scenario)
