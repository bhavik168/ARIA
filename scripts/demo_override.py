#!/usr/bin/env python3
"""
ARIA Demo — Dispatcher Override Flow (Narrated)

Shows what happens when a dispatcher disagrees with ARIA's recommendation.
Can reuse an incident from a previous demo or start a fresh one.

Usage:
    python scripts/demo_override.py
    python scripts/demo_override.py --incident-id INC-... --api-url https://...
"""
import argparse
import boto3
import json
import os
import sys
import time
import urllib.request
import urllib.error

REGION = os.environ.get("AWS_REGION", "us-east-1")

RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"


def _banner():
    print(f"\n{BOLD}{YELLOW}{'='*60}{RESET}")
    print(f"{BOLD}  ARIA — Emergency Dispatch Intelligence{RESET}")
    print(f"{BOLD}  Demo: Dispatcher Override Flow{RESET}")
    print(f"{BOLD}{YELLOW}{'='*60}{RESET}\n")


def _step(label: str, detail: str = ""):
    ts = time.strftime("%H:%M:%S")
    print(f"{DIM}{ts}{RESET}  {CYAN}{BOLD}{label}{RESET}  {DIM}{detail}{RESET}")


def _ok(label: str, detail: str = ""):
    ts = time.strftime("%H:%M:%S")
    print(f"{DIM}{ts}{RESET}  {GREEN}✓ {label}{RESET}  {detail}")


def _get_api_url() -> str:
    if os.environ.get("ARIA_API_URL"):
        return os.environ["ARIA_API_URL"].rstrip("/")
    try:
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for o in stacks[0].get("Outputs", []):
            if o["OutputKey"] == "RestApiUrl":
                return o["OutputValue"].rstrip("/")
    except Exception:
        pass
    return ""


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()[:200]}


def _start_fresh_session() -> str:
    scenario = {
        "simulation_transcript": [
            {"word": "1420", "speaker": "caller", "delay_ms": 0},
            {"word": "East", "speaker": "caller", "delay_ms": 300},
            {"word": "Pike", "speaker": "caller", "delay_ms": 200},
            {"word": "Street", "speaker": "caller", "delay_ms": 200},
            {"word": "not", "speaker": "caller", "delay_ms": 500},
            {"word": "breathing", "speaker": "caller", "delay_ms": 300},
        ]
    }
    lam = boto3.client("lambda", region_name=REGION)
    resp = lam.invoke(
        FunctionName="aria-ingest",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": "/session/start",
            "body": json.dumps(scenario),
        }).encode(),
    )
    result = json.loads(resp["Payload"].read())
    body = json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result
    return body.get("incident_id") or result.get("incident_id", "")


def _get_incident(incident_id: str) -> dict:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    resp = ddb.Table("aria-incidents").get_item(
        Key={"incident_id": incident_id, "timestamp": "latest"}
    )
    return resp.get("Item", {})


def _get_overrides(incident_id: str) -> list:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    resp = ddb.Table("aria-overrides").query(
        KeyConditionExpression="incident_id = :id",
        ExpressionAttributeValues={":id": incident_id},
    )
    return resp.get("Items", [])


def run_demo(incident_id: str, api_url: str):
    _banner()

    # If no incident ID, start a fresh one
    if not incident_id:
        _step("SETUP", "No incident_id provided — starting a fresh session...")
        incident_id = _start_fresh_session()
        if not incident_id:
            print(f"{RED}Could not start session. Is the stack deployed?{RESET}")
            sys.exit(1)
        _ok("Session started", f"incident_id={incident_id}")
        print(f"\n  {DIM}Waiting 12s for pipeline to run...{RESET}")
        time.sleep(12)
        print()

    print(f"{BOLD}Incident ID:{RESET} {incident_id}\n")
    print(f"{DIM}{'─'*60}{RESET}\n")

    # Step 1 — Show ARIA's recommendation
    _step("STEP 1", "Reading ARIA's current recommendation from DynamoDB...")
    item = _get_incident(incident_id)
    nav = item.get("navigation_result", {})
    med = item.get("medical_result", {})

    print(f"\n  {BOLD}ARIA recommends:{RESET}")
    if nav:
        print(f"  → Unit:      {nav.get('unit_id', '?')} ({nav.get('unit_type', '?')}), ETA {nav.get('eta_minutes', '?')} min")
    if med:
        hosp = med.get("recommended_hospital", {})
        print(f"  → Hospital:  {hosp.get('name', '?')}, ETA {hosp.get('eta_minutes', '?')} min")
    print()

    # Step 2 — Dispatcher first approves Navigation (partial approval)
    _step("STEP 2", "Dispatcher clicks 'DISPATCH UNIT NOW' (partial approval)...")
    time.sleep(1)

    if api_url:
        result = _post(f"{api_url}/session/{incident_id}/approve", {"partial": True})
        _ok("Partial approval sent", f"status={result.get('status', '?')}")
    else:
        # Direct DynamoDB for local demo
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.Table("aria-incidents").update_item(
            Key={"incident_id": incident_id, "timestamp": "latest"},
            UpdateExpression="SET dispatcher_approved = :t",
            ExpressionAttributeValues={":t": True},
        )
        _ok("dispatcher_approved = True", "written directly to DynamoDB")
    print()

    # Step 3 — Dispatcher overrides the hospital choice
    _step("STEP 3", "Dispatcher disagrees with hospital choice — submitting override...")
    time.sleep(1)

    override_body = {
        "override_reason": "Hospital preference",
        "dispatcher_choice": {
            "hospital_id": "H002",
            "name": "UW Medical Center",
            "notes": "Closer to incident, trauma team just came on shift",
        },
        "notes": "UW has better burn coverage for this call type",
    }

    print(f"\n  {BOLD}Override payload:{RESET}")
    print(f"  Reason:   {override_body['override_reason']}")
    print(f"  Choice:   {override_body['dispatcher_choice']['name']}")
    print(f"  Notes:    {override_body['notes']}\n")

    if api_url:
        result = _post(f"{api_url}/session/{incident_id}/override", override_body)
        _ok("Override submitted via REST API", f"status={result.get('status', '?')}")
    else:
        # Direct Lambda invoke
        lam = boto3.client("lambda", region_name=REGION)
        lam.invoke(
            FunctionName="aria-coordinator",
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "httpMethod": "POST",
                "path": f"/session/{incident_id}/override",
                "pathParameters": {"id": incident_id},
                "body": json.dumps(override_body),
            }).encode(),
        )
        _ok("Override submitted via Lambda", "")
    print()

    # Step 4 — Verify override logged in DynamoDB
    _step("STEP 4", "Verifying override record written to aria-overrides table...")
    time.sleep(1)
    overrides = _get_overrides(incident_id)
    if overrides:
        latest = overrides[-1]
        _ok("Override logged in DynamoDB")
        print(f"  reason:    {latest.get('override_reason', '?')}")
        print(f"  timestamp: {latest.get('timestamp', '?')}")
        print(f"  choice:    {json.dumps(latest.get('dispatcher_choice', {}))[:80]}")
    else:
        print(f"  {YELLOW}⚠ Override not found in DynamoDB — verify OVERRIDES_TABLE env var{RESET}")
    print()

    print(f"{DIM}{'─'*60}{RESET}")
    print(f"\n{BOLD}Override demo complete{RESET}")
    print(f"{BOLD}incident_id:{RESET} {incident_id}")
    print(f"\n{DIM}This override record is available for post-incident review and model improvement.{RESET}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARIA dispatcher override demo")
    parser.add_argument("--incident-id", default="", help="Reuse an existing incident ID")
    parser.add_argument("--api-url", default="", help="REST API base URL (optional)")
    args = parser.parse_args()

    api_url = args.api_url or os.environ.get("ARIA_API_URL", "")
    run_demo(args.incident_id, api_url)
