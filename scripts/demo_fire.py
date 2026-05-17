#!/usr/bin/env python3
"""
ARIA Demo — Structure Fire + Hazmat Scenario (Narrated)

Runs the full pipeline with the SoDo warehouse fire simulation.
Shows Fire/Hazmat Agent returning evacuation radius and PPE recommendations.

Usage:
    python scripts/demo_fire.py
"""
import boto3
import json
import os
import sys
import time

REGION = os.environ.get("AWS_REGION", "us-east-1")
SCENARIO_FILE = "audio-samples/sim_structure_fire.json"

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
ORANGE = "\033[38;5;208m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _load_scenario() -> dict:
    with open(SCENARIO_FILE) as f:
        return json.load(f)


def _banner():
    print(f"\n{BOLD}{ORANGE}{'='*60}{RESET}")
    print(f"{BOLD}  ARIA — Emergency Dispatch Intelligence{RESET}")
    print(f"{BOLD}  Demo: Structure Fire — SoDo Warehouse, Seattle{RESET}")
    print(f"{BOLD}{ORANGE}{'='*60}{RESET}\n")


def _step(label: str, detail: str = ""):
    ts = time.strftime("%H:%M:%S")
    print(f"{DIM}{ts}{RESET}  {ORANGE}{BOLD}{label}{RESET}  {DIM}{detail}{RESET}")


def _ok(label: str, detail: str = ""):
    ts = time.strftime("%H:%M:%S")
    print(f"{DIM}{ts}{RESET}  {GREEN}✓ {label}{RESET}  {detail}")


def _warn(label: str, detail: str = ""):
    ts = time.strftime("%H:%M:%S")
    print(f"{DIM}{ts}{RESET}  {YELLOW}⚠ {label}{RESET}  {detail}")


def _poll_dynamodb(incident_id: str, field: str, timeout: int = 30) -> dict:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table("aria-incidents")
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = table.get_item(Key={"incident_id": incident_id, "timestamp": "latest"})
        item = resp.get("Item", {})
        if item.get(field):
            return item
        time.sleep(1)
    return {}


def _invoke_ingest(transcript: list) -> dict:
    lam = boto3.client("lambda", region_name=REGION)
    resp = lam.invoke(
        FunctionName="aria-ingest",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": "/session/start",
            "body": json.dumps({"simulation_transcript": transcript}),
        }).encode(),
    )
    return json.loads(resp["Payload"].read())


def run_demo():
    _banner()
    scenario = _load_scenario()
    t_global = time.time()

    print(f"{BOLD}Scenario:{RESET} {scenario['description']}")
    print(f"{BOLD}Expected watchers:{RESET} {', '.join(scenario['expected_watchers'])}")
    print(f"{BOLD}This scenario triggers:{RESET} FireWatcher → Hazmat Agent\n")
    print(f"{DIM}{'─'*60}{RESET}\n")

    # Step 1 — Start session
    _step("STEP 1", "Starting 911 call session")
    t0 = time.time()
    try:
        result = _invoke_ingest(scenario["transcript"])
        body = json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result
        incident_id = body.get("incident_id") or result.get("incident_id")
        if not incident_id:
            print(f"{RED}ERROR: No incident_id returned.{RESET}")
            sys.exit(1)
    except Exception as e:
        print(f"{RED}ERROR invoking aria-ingest: {e}{RESET}")
        sys.exit(1)

    _ok("Session started", f"incident_id={incident_id}  ({time.time()-t0:.2f}s)")
    print()

    # Step 2 — Navigation
    _step("STEP 2", "Waiting for Navigation Agent (fire_engine + ladder unit selection)...")
    t_nav = time.time()
    item = _poll_dynamodb(incident_id, "navigation_result", timeout=25)
    nav = item.get("navigation_result", {})
    if nav:
        _ok("Navigation Agent complete", f"+{time.time()-t_nav:.1f}s")
        print(f"  {BOLD}Unit:{RESET}  {nav.get('unit_id', '?')} ({nav.get('unit_type', '?')})")
        print(f"  {BOLD}ETA:{RESET}   {nav.get('eta_minutes', '?')} minutes")
    else:
        _warn("Navigation Agent", "timed out — check Lambda logs")
    print()

    # Step 3 — Hazmat
    _step("STEP 3", "Waiting for Fire/Hazmat Agent (FEMA ERG KB + PPE recommendations)...")
    t_haz = time.time()
    item = _poll_dynamodb(incident_id, "hazmat_result", timeout=30)
    haz = item.get("hazmat_result", {})
    if haz:
        _ok("Fire/Hazmat Agent complete", f"+{time.time()-t_haz:.1f}s")
        print(f"  {BOLD}Hazard type:{RESET}        {haz.get('hazard_type', '?')}")
        print(f"  {BOLD}Evacuation radius:{RESET}  {haz.get('evacuation_radius_meters', '?')}m")
        ppe = haz.get('protective_equipment', [])
        print(f"  {BOLD}Required PPE:{RESET}       {', '.join(ppe)}")
        approach = haz.get("suppression_approach", "")
        if approach:
            print(f"  {BOLD}Approach:{RESET}           {approach[:100]}")
        if haz.get("kb_excerpt"):
            print(f"  {BOLD}KB source:{RESET}          {haz.get('source_document', 'default-sop')}")
    else:
        _warn("Hazmat Agent", "timed out")
    print()

    # Step 4 — Coordinator
    _step("STEP 4", "Waiting for Coordinator card...")
    item = _poll_dynamodb(incident_id, "recommendation_ready", timeout=40)
    total_elapsed = time.time() - t_global
    if item.get("recommendation_ready"):
        _ok("Recommendation card ready", f"Total: {total_elapsed:.1f}s")
    else:
        _warn("Coordinator", f"not ready within 40s — partial results available")
    print()

    print(f"{DIM}{'─'*60}{RESET}")
    print(f"\n{BOLD}Demo complete{RESET} — {total_elapsed:.1f}s")
    print(f"{BOLD}incident_id:{RESET} {incident_id}\n")


if __name__ == "__main__":
    run_demo()
