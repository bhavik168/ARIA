#!/usr/bin/env python3
"""
Full pipeline test: simulation transcript → ingest → stream-processor → all agents → coordinator card.

Runs all 3 Seattle demo scenarios and validates the recommendation card for each.

Usage:
    python scripts/test_full_pipeline.py
    python scripts/test_full_pipeline.py --scenario cardiac_arrest
    python scripts/test_full_pipeline.py --local    # invoke Lambda directly, skip API Gateway
"""
import argparse
import boto3
import json
import sys
import time
from pathlib import Path

REGION = "us-east-1"
AUDIO_SAMPLES_DIR = Path(__file__).parent.parent / "audio-samples"

SCENARIOS = {
    "cardiac_arrest": {
        "file": "sim_cardiac_arrest.json",
        "expect_nav": True,
        "expect_med": True,
        "expect_haz": False,
        "wait_s": 35,
    },
    "hazmat_port": {
        "file": "sim_hazmat_port.json",
        "expect_nav": True,
        "expect_med": False,
        "expect_haz": True,
        "wait_s": 35,
    },
    "structure_fire": {
        "file": "sim_structure_fire.json",
        "expect_nav": True,
        "expect_med": False,
        "expect_haz": True,
        "wait_s": 30,
    },
}


def load_scenario(name: str) -> dict:
    cfg = SCENARIOS[name]
    with open(AUDIO_SAMPLES_DIR / cfg["file"]) as f:
        sim = json.load(f)
    return {**cfg, "transcript": sim["transcript"], "description": sim.get("description", name)}


def invoke_ingest(transcript: list, local: bool) -> str:
    payload_body = {"simulation_transcript": transcript}

    if local:
        client = boto3.client("lambda", region_name=REGION)
        resp = client.invoke(
            FunctionName="aria-ingest",
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "httpMethod": "POST",
                "path": "/session/start",
                "body": json.dumps(payload_body),
            }).encode(),
        )
        body = json.loads(json.loads(resp["Payload"].read())["body"])
    else:
        import urllib.request
        import os
        api_url = os.environ.get("ARIA_API_URL", "").rstrip("/")
        if not api_url:
            try:
                cf = boto3.client("cloudformation", region_name=REGION)
                stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
                for o in stacks[0].get("Outputs", []):
                    if o["OutputKey"] == "RestApiUrl":
                        api_url = o["OutputValue"].rstrip("/")
            except Exception:
                pass
        if not api_url:
            print("ERROR: Set ARIA_API_URL or use --local", file=sys.stderr)
            sys.exit(1)
        req = urllib.request.Request(
            f"{api_url}/session/start",
            data=json.dumps(payload_body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            body = json.loads(r.read())

    return body["incident_id"]


def poll_incident(incident_id: str, wait_s: int) -> dict:
    """Poll DynamoDB directly until recommendation_card appears or timeout."""
    table = boto3.resource("dynamodb", region_name=REGION).Table("aria-incidents")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        resp = table.query(
            KeyConditionExpression="incident_id = :id",
            ExpressionAttributeValues={":id": incident_id},
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if items and items[0].get("recommendation_card"):
            return items[0]
        time.sleep(2)
    # Return whatever we have even if incomplete
    items = table.query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
        ScanIndexForward=False,
        Limit=1,
    ).get("Items", [{}])
    return items[0] if items else {}


def validate(scenario_name: str, cfg: dict, item: dict) -> list:
    errors = []
    card = item.get("recommendation_card")

    if not card:
        errors.append("recommendation_card never appeared in DynamoDB")
        return errors

    if cfg["expect_nav"] and not item.get("navigation_result"):
        errors.append("navigation_result missing — LocationWatcher may not have fired")
    if cfg["expect_med"] and not item.get("medical_result"):
        errors.append("medical_result missing — MedicalWatcher may not have fired")
    if cfg["expect_haz"] and not item.get("hazmat_result"):
        errors.append("hazmat_result missing — FireWatcher/HazmatWatcher may not have fired")
    if not card.get("recommended_unit"):
        errors.append("recommended_unit missing from card")
    if cfg["expect_med"] and not card.get("recommended_hospital"):
        errors.append("recommended_hospital missing from card for medical scenario")

    # Latency checks from DynamoDB timestamps
    t0 = item.get("t0_ms", 0)
    nav_ms = item.get("navigation_at_ms", 0)
    card_ms = item.get("recommendation_ready_at_ms", 0)
    if t0 and nav_ms and (nav_ms - t0) > 15000:
        errors.append(f"navigation_at_ms too slow: {nav_ms - t0}ms (target <15000ms)")
    if t0 and card_ms and (card_ms - t0) > 20000:
        errors.append(f"recommendation_card too slow: {card_ms - t0}ms (target <20000ms)")

    return errors


def run_scenario(name: str, local: bool) -> bool:
    cfg = load_scenario(name)
    print(f"\n{'='*55}")
    print(f"Scenario: {name}")
    print(f"  {cfg['description']}")
    print(f"  Words: {len(cfg['transcript'])} | Wait: {cfg['wait_s']}s")

    t0 = time.time()
    incident_id = invoke_ingest(cfg["transcript"], local)
    print(f"  incident_id: {incident_id}")
    print(f"  Waiting for pipeline to complete...")

    item = poll_incident(incident_id, cfg["wait_s"])
    elapsed = round(time.time() - t0, 1)

    card = item.get("recommendation_card", {})
    nav = item.get("navigation_result", {})
    med = item.get("medical_result", {})
    haz = item.get("hazmat_result", {})

    print(f"\n  Pipeline elapsed: {elapsed}s")
    print(f"  Recommendation card: {'✓' if card else '✗ missing'}")
    if card:
        print(f"    incident_type:   {card.get('incident_type', 'N/A')}")
        print(f"    severity:        {card.get('severity', 'N/A')}")
        print(f"    ai_confidence:   {card.get('ai_confidence', 'N/A')}")
        unit = card.get("recommended_unit") or {}
        print(f"    recommended_unit: {unit.get('unit_id', 'N/A')} — ETA {unit.get('eta_minutes', 'N/A')} min")
        hosp = card.get("recommended_hospital") or {}
        if hosp:
            print(f"    hospital:        {hosp.get('name', 'N/A')} — ETA {hosp.get('eta_minutes', 'N/A')} min")
    if nav:
        print(f"  Navigation:  ✓ {nav.get('unit_id', '')} — {nav.get('eta_minutes', '?')} min")
    if med:
        h = med.get("recommended_hospital", {})
        print(f"  Medical:     ✓ {h.get('name', '')} — pre-alert: {med.get('pre_alert_status', {}).get('status', '?')}")
    if haz:
        print(f"  Hazmat:      ✓ radius {haz.get('evacuation_radius_meters', '?')}m — {haz.get('hazard_type', '?')}")

    errors = validate(name, cfg, item)
    if errors:
        print(f"\n  FAILURES ({len(errors)}):")
        for e in errors:
            print(f"    ✗ {e}")
        return False
    else:
        print(f"\n  ✓ {name} PASSED ({elapsed}s)")
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARIA full pipeline test")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()),
                        help="Run a single scenario (default: all three)")
    parser.add_argument("--local", action="store_true",
                        help="Invoke Lambda directly via boto3")
    args = parser.parse_args()

    to_run = [args.scenario] if args.scenario else list(SCENARIOS.keys())
    results = {}

    for name in to_run:
        results[name] = run_scenario(name, args.local)

    print(f"\n{'='*55}")
    print("SUMMARY")
    passed = sum(1 for v in results.values() if v)
    for name, ok in results.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    print(f"\n{passed}/{len(results)} scenarios passed")

    if passed < len(results):
        sys.exit(1)
