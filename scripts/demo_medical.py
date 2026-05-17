#!/usr/bin/env python3
"""
ARIA Demo — Cardiac Arrest Scenario (Narrated)

Runs the full pipeline with the cardiac arrest simulation.
Prints each step with real-time timing as it happens.

Usage:
    python scripts/demo_medical.py
    python scripts/demo_medical.py --local   # invoke Lambda directly via boto3
"""
import argparse
import boto3
import json
import os
import sys
import time

REGION = os.environ.get("AWS_REGION", "us-east-1")
SCENARIO_FILE = "audio-samples/sim_cardiac_arrest.json"

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _load_scenario() -> dict:
    with open(SCENARIO_FILE) as f:
        return json.load(f)


def _banner():
    print(f"\n{BOLD}{RED}{'='*60}{RESET}")
    print(f"{BOLD}  ARIA — Emergency Dispatch Intelligence{RESET}")
    print(f"{BOLD}  Demo: Cardiac Arrest — Capitol Hill, Seattle{RESET}")
    print(f"{BOLD}{RED}{'='*60}{RESET}\n")


def _step(label: str, detail: str = "", color: str = CYAN):
    ts = time.strftime("%H:%M:%S")
    print(f"{DIM}{ts}{RESET}  {color}{BOLD}{label}{RESET}  {DIM}{detail}{RESET}")


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
    payload = {"simulation_transcript": transcript}
    resp = lam.invoke(
        FunctionName="aria-ingest",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": "/session/start",
            "body": json.dumps(payload),
        }).encode(),
    )
    return json.loads(resp["Payload"].read())


def run_demo():
    _banner()
    scenario = _load_scenario()
    t_global = time.time()

    print(f"{BOLD}Scenario:{RESET} {scenario['description']}")
    print(f"{BOLD}Expected watchers:{RESET} {', '.join(scenario['expected_watchers'])}")
    print(f"{BOLD}Expected agents:{RESET} {', '.join(scenario['expected_agents'])}\n")
    print(f"{DIM}{'─'*60}{RESET}\n")

    # Step 1 — Start session
    _step("STEP 1", "Starting 911 call session via aria-ingest Lambda")
    t0 = time.time()
    try:
        result = _invoke_ingest(scenario["transcript"])
        body = json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result
        incident_id = body.get("incident_id") or result.get("incident_id")
        if not incident_id:
            print(f"{RED}ERROR: No incident_id returned. Is the stack deployed?{RESET}")
            print(f"Response: {result}")
            sys.exit(1)
    except Exception as e:
        print(f"{RED}ERROR invoking aria-ingest: {e}{RESET}")
        print("Make sure AWS credentials are set and the stack is deployed.")
        sys.exit(1)

    elapsed = time.time() - t0
    _ok("Session started", f"incident_id={incident_id}  ({elapsed:.2f}s)")
    print()

    # Step 2 — Watch transcript words replay
    _step("STEP 2", "Replaying transcript word-by-word (stream processor running)...")
    word_count = len(scenario["transcript"])
    total_delay_ms = sum(w.get("delay_ms", 0) for w in scenario["transcript"])
    print(f"  {word_count} words · ~{total_delay_ms/1000:.1f}s total call duration")
    print(f"  {DIM}Watching for watcher triggers in DynamoDB...{RESET}\n")

    # Wait for stream processing to begin
    time.sleep(2)
    _ok("Stream processor", "words flowing through domain watchers")
    print()

    # Step 3 — Wait for navigation result
    _step("STEP 3", "Waiting for Navigation Agent (LocationWatcher → Google Maps ETA)...")
    t_nav = time.time()
    item = _poll_dynamodb(incident_id, "navigation_result", timeout=25)
    nav = item.get("navigation_result", {})
    if nav:
        elapsed = time.time() - t_nav
        _ok("Navigation Agent complete", f"+{elapsed:.1f}s from trigger")
        print(f"  {BOLD}Unit:{RESET}     {nav.get('unit_id', '?')} ({nav.get('unit_type', '?')})")
        print(f"  {BOLD}ETA:{RESET}      {nav.get('eta_minutes', '?')} minutes")
        if nav.get("turn_by_turn_url"):
            print(f"  {BOLD}Route:{RESET}    {nav['turn_by_turn_url'][:70]}...")
    else:
        _warn("Navigation Agent", "did not return within 25s — check Lambda logs")
    print()

    # Step 4 — Wait for medical result
    _step("STEP 4", "Waiting for Medical Agent (MedicalWatcher → KB + Hospital pre-alert)...")
    t_med = time.time()
    item = _poll_dynamodb(incident_id, "medical_result", timeout=30)
    med = item.get("medical_result", {})
    if med:
        elapsed = time.time() - t_med
        hosp = med.get("recommended_hospital", {})
        _ok("Medical Agent complete", f"+{elapsed:.1f}s from trigger")
        print(f"  {BOLD}Hospital:{RESET}  {hosp.get('name', '?')}")
        print(f"  {BOLD}ETA:{RESET}       {hosp.get('eta_minutes', '?')} minutes")
        print(f"  {BOLD}ER status:{RESET} {hosp.get('er_status', '?')}")
        print(f"  {BOLD}Protocol:{RESET}  {str(med.get('triage_protocol', ''))[:80]}...")
    else:
        _warn("Medical Agent", "did not return within 30s — check Lambda logs")
    print()

    # Step 5 — Wait for coordinator card
    _step("STEP 5", "Waiting for Coordinator to synthesize final recommendation card...")
    t_coord = time.time()
    item = _poll_dynamodb(incident_id, "recommendation_ready", timeout=40)
    if item.get("recommendation_ready"):
        elapsed = time.time() - t_coord
        total_elapsed = time.time() - t_global
        _ok("Recommendation card ready", f"+{elapsed:.1f}s | Total: {total_elapsed:.1f}s from session start")
        card = item.get("recommendation_card", {})
        if card:
            print(f"  {BOLD}Severity:{RESET}    {card.get('severity', '?').upper()}")
            print(f"  {BOLD}Confidence:{RESET}  {card.get('ai_confidence', '?')}")
            print(f"  {BOLD}Reasoning:{RESET}   {card.get('reasoning_summary', '')[:100]}")
    else:
        _warn("Coordinator", "card not ready within 40s — partial results above are still valid for demo")
    print()

    # Summary
    total_elapsed = time.time() - t_global
    print(f"{DIM}{'─'*60}{RESET}")
    print(f"\n{BOLD}Demo complete{RESET} — {total_elapsed:.1f}s total wall time")
    print(f"{BOLD}incident_id:{RESET} {incident_id}")
    print(f"\n{DIM}Next: run demo_override.py with this incident_id to show override flow{RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARIA cardiac arrest demo")
    parser.parse_args()
    run_demo()
