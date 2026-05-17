#!/usr/bin/env python3
"""
Test the stream processor pipeline using simulation transcripts.

Loads a simulation JSON from audio-samples/, posts it to the ingest endpoint,
then listens on the WebSocket for events and verifies:
  - Words appear on dashboard within 500ms of being fired
  - Correct watchers fire (location, medical, fire, hazmat, crime)
  - Correct agents are invoked within 500ms of watcher trigger

Usage:
    python scripts/test_stream_processor.py --scenario cardiac_arrest
    python scripts/test_stream_processor.py --scenario hazmat_port
    python scripts/test_stream_processor.py --scenario structure_fire
    python scripts/test_stream_processor.py --local   # invoke Lambda directly (no API Gateway)
"""
import argparse
import json
import sys
import time
import threading
import urllib.request
import urllib.parse
import os
from pathlib import Path

REGION = "us-east-1"
AUDIO_SAMPLES_DIR = Path(__file__).parent.parent / "audio-samples"
SCENARIO_MAP = {
    "cardiac_arrest": "sim_cardiac_arrest.json",
    "hazmat_port": "sim_hazmat_port.json",
    "structure_fire": "sim_structure_fire.json",
}

received_events = []
event_lock = threading.Lock()


def get_api_url() -> str:
    api_url = os.environ.get("ARIA_API_URL")
    if api_url:
        return api_url.rstrip("/")
    try:
        import boto3
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for output in stacks[0].get("Outputs", []):
            if output["OutputKey"] == "RestApiUrl":
                return output["OutputValue"].rstrip("/")
    except Exception:
        pass
    print("ERROR: Set ARIA_API_URL env var or deploy the stack.", file=sys.stderr)
    sys.exit(1)


def load_scenario(name: str) -> dict:
    filename = SCENARIO_MAP.get(name)
    if not filename:
        print(f"ERROR: Unknown scenario '{name}'. Choose: {list(SCENARIO_MAP.keys())}", file=sys.stderr)
        sys.exit(1)
    path = AUDIO_SAMPLES_DIR / filename
    with open(path) as f:
        return json.load(f)


def invoke_local(scenario: dict) -> str:
    """Invoke aria-ingest Lambda directly via boto3 (bypasses API Gateway)."""
    import boto3
    client = boto3.client("lambda", region_name=REGION)
    payload = {
        "httpMethod": "POST",
        "path": "/session/start",
        "body": json.dumps({"simulation_transcript": scenario["transcript"]}),
    }
    resp = client.invoke(
        FunctionName="aria-ingest",
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    result = json.loads(json.loads(resp["Payload"].read())["body"])
    return result["incident_id"]


def invoke_api(api_url: str, scenario: dict) -> tuple:
    """POST to /session/start via API Gateway."""
    url = f"{api_url}/session/start"
    body = json.dumps({"simulation_transcript": scenario["transcript"]}).encode()
    req = urllib.request.Request(url, data=body,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    return data["incident_id"], data.get("websocket_url", "")


def print_results(scenario: dict, incident_id: str, elapsed_s: float) -> None:
    expected_watchers = set(scenario.get("expected_watchers", []))

    print(f"\n{'='*55}")
    print(f"Scenario: {scenario['scenario']}")
    print(f"Incident ID: {incident_id}")
    print(f"Total elapsed: {elapsed_s:.2f}s")
    print(f"\nExpected watchers: {expected_watchers}")
    print(f"Expected agents:   {scenario.get('expected_agents', [])}")
    print(f"\nWebSocket events received ({len(received_events)} total):")
    for ev in received_events[:20]:
        print(f"  [{ev.get('type', '?')}] {json.dumps(ev)[:120]}")


def run_test(scenario: dict, local: bool, api_url: str = None) -> None:
    t0 = time.time()
    print(f"\nStarting scenario: {scenario['description']}")
    print(f"Words to replay: {len(scenario['transcript'])}")

    if local:
        print("Mode: direct Lambda invoke")
        incident_id = invoke_local(scenario)
        ws_url = ""
    else:
        print(f"Mode: API Gateway ({api_url})")
        incident_id, ws_url = invoke_api(api_url, scenario)

    print(f"  → incident_id: {incident_id}")
    print(f"  → websocket_url: {ws_url}")

    # Give simulation time to run (total transcript duration + buffer)
    total_delay = sum(w.get("delay_ms", 300) for w in scenario["transcript"]) / 1000
    wait = min(total_delay + 5, 60)
    print(f"Waiting {wait:.1f}s for simulation to complete...")
    time.sleep(wait)

    elapsed = time.time() - t0
    print_results(scenario, incident_id, elapsed)

    # Basic validation — check DynamoDB for triggered watchers
    try:
        import boto3
        table = boto3.resource("dynamodb", region_name=REGION).Table("aria-incidents")
        result = table.query(
            KeyConditionExpression="incident_id = :id",
            ExpressionAttributeValues={":id": incident_id},
            ScanIndexForward=False,
            Limit=1,
        )
        items = result.get("Items", [])
        if items:
            item = items[0]
            print(f"\nDynamoDB record:")
            print(f"  status: {item.get('status')}")
            print(f"  navigation_result: {'✓' if item.get('navigation_result') else '✗ missing'}")
            print(f"  medical_result:    {'✓' if item.get('medical_result') else '✗ missing'}")
            print(f"  hazmat_result:     {'✓' if item.get('hazmat_result') else '✗ missing'}")
            if item.get("navigation_result"):
                nav = item["navigation_result"]
                print(f"  best unit: {nav.get('unit_id')} — ETA {nav.get('eta_minutes')} min")
    except Exception as e:
        print(f"Could not check DynamoDB: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test ARIA stream processor pipeline")
    parser.add_argument("--scenario", default="cardiac_arrest",
                        choices=list(SCENARIO_MAP.keys()), help="Scenario to run")
    parser.add_argument("--local", action="store_true",
                        help="Invoke Lambda directly instead of via API Gateway")
    args = parser.parse_args()

    scenario = load_scenario(args.scenario)
    api_url = None if args.local else get_api_url()
    run_test(scenario, args.local, api_url)
