#!/usr/bin/env python3
"""
Test aria-hazmat-tool directly with synthetic Seattle incident payloads.

Usage:
    python scripts/test_agent_hazmat.py
    python scripts/test_agent_hazmat.py --scenario structure_fire
"""
import argparse
import boto3
import json
import sys
import time

REGION = "us-east-1"

SCENARIOS = {
    "chlorine_port": {
        "incident_id": f"test-haz-chlorine-{int(time.time())}",
        "context_so_far": (
            "There's a chemical spill at Terminal 18 Port of Seattle "
            "I can see yellow fumes coming from a container workers are coughing "
            "I think it's chlorine"
        ),
        "trigger_reason": "hazmat_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "hazmat",
            "severity": "critical",
            "location": {"address": "Terminal 18, Port of Seattle, WA", "lat": 47.5778, "lng": -122.3519},
        },
    },
    "structure_fire": {
        "incident_id": f"test-haz-fire-{int(time.time())}",
        "context_so_far": (
            "There's smoke pouring out of a building on 1st Avenue South "
            "looks like a warehouse there's fire on the second floor flames visible"
        ),
        "trigger_reason": "fire_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "fire",
            "severity": "urgent",
            "location": {"address": "1st Ave S, Seattle, WA 98134", "lat": 47.5951, "lng": -122.3313},
        },
    },
    "gas_leak": {
        "incident_id": f"test-haz-gas-{int(time.time())}",
        "context_so_far": (
            "I can smell gas really strongly in my apartment building "
            "on Eastlake Avenue there's a strong gas leak smell on the whole floor"
        ),
        "trigger_reason": "hazmat_keyword_detected",
        "triggered_at_ms": int(time.time() * 1000),
        "incident_data": {
            "incident_type": "hazmat",
            "severity": "urgent",
            "location": {"address": "2200 Eastlake Ave E, Seattle, WA", "lat": 47.6380, "lng": -122.3280},
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

    print(f"Testing aria-hazmat-tool — scenario: {scenario_name}")
    print(f"  Incident ID: {incident_id}")
    print(f"  Trigger:     {payload['trigger_reason']}")
    print(f"  Context:     {payload['context_so_far'][:80]}...")
    print()

    t0 = time.time()
    resp = client.invoke(
        FunctionName="aria-hazmat-tool",
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    elapsed = round((time.time() - t0) * 1000)
    result = json.loads(resp["Payload"].read())

    print(f"Elapsed: {elapsed}ms")
    print(f"Status:  {result.get('status')}")
    print()
    print(f"Hazard type:          {result.get('hazard_type', 'N/A')}")
    print(f"Evacuation radius:    {result.get('evacuation_radius_meters', 'N/A')} meters")
    print(f"Protective equipment: {result.get('protective_equipment', [])}")
    print(f"Suppression approach: {result.get('suppression_approach', 'N/A')[:100]}")
    print(f"FEMA ERG guide:       {result.get('fema_erg_guide_number', 'N/A')}")
    print(f"Source document:      {result.get('source_document', 'N/A')}")
    if result.get("kb_excerpt"):
        print(f"\nKB excerpt: {result['kb_excerpt'][:200]}...")

    # Validate
    errors = []
    if result.get("status") != "ok":
        errors.append(f"status was '{result.get('status')}', expected 'ok'")
    if not result.get("evacuation_radius_meters"):
        errors.append("evacuation_radius_meters missing")
    if not result.get("protective_equipment"):
        errors.append("protective_equipment missing")
    if not result.get("suppression_approach"):
        errors.append("suppression_approach missing")

    print()
    if errors:
        print("FAILURES:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)
    else:
        print("✓ Hazmat agent test passed")
        radius = result.get("evacuation_radius_meters")
        erg = result.get("fema_erg_guide_number")
        print(f"  Evacuation radius: {radius}m")
        if erg:
            print(f"  FEMA ERG Guide:    {erg} ✓")
        source = result.get("source_document", "")
        if source and source not in ("default-sop", "fallback"):
            print(f"  KB source:         {source} ✓")
        else:
            print(f"  KB source:         default (sync KB to get ERG citations)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test aria-hazmat-tool Lambda")
    parser.add_argument("--scenario", default="chlorine_port", choices=list(SCENARIOS.keys()))
    args = parser.parse_args()
    run_test(args.scenario)
