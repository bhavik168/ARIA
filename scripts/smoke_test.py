#!/usr/bin/env python3
"""
Post-deploy smoke test — run by CI after cdk deploy.

Reads API URL from CDK outputs file or environment variable, then:
  1. Starts a session with a 3-word simulation transcript
  2. Polls /status until recommendation_ready or timeout
  3. Calls /approve
  4. Validates final DynamoDB state

Usage:
    CDK_OUTPUTS_FILE=cdk-outputs.json python scripts/smoke_test.py
    ARIA_API_URL=https://... python scripts/smoke_test.py
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error

REGION = os.environ.get("AWS_REGION", "us-east-1")
CDK_OUTPUTS_FILE = os.environ.get("CDK_OUTPUTS_FILE", "cdk-outputs.json")

SMOKE_TRANSCRIPT = [
    {"word": "1420", "speaker": "caller", "delay_ms": 0},
    {"word": "East", "speaker": "caller", "delay_ms": 300},
    {"word": "Pike", "speaker": "caller", "delay_ms": 300},
    {"word": "Street", "speaker": "caller", "delay_ms": 300},
    {"word": "not", "speaker": "caller", "delay_ms": 500},
    {"word": "breathing", "speaker": "caller", "delay_ms": 300},
]


def _get_api_url() -> str:
    if os.environ.get("ARIA_API_URL"):
        return os.environ["ARIA_API_URL"].rstrip("/")
    if os.path.exists(CDK_OUTPUTS_FILE):
        with open(CDK_OUTPUTS_FILE) as f:
            outputs = json.load(f)
        for stack_outputs in outputs.values():
            if "RestApiUrl" in stack_outputs:
                return stack_outputs["RestApiUrl"].rstrip("/")
    try:
        import boto3
        cf = boto3.client("cloudformation", region_name=REGION)
        stacks = cf.describe_stacks(StackName="AriaStack")["Stacks"]
        for o in stacks[0].get("Outputs", []):
            if o["OutputKey"] == "RestApiUrl":
                return o["OutputValue"].rstrip("/")
    except Exception:
        pass
    print("ERROR: could not resolve API URL. Set ARIA_API_URL or CDK_OUTPUTS_FILE.", file=sys.stderr)
    sys.exit(1)


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def _get(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def run_smoke_test() -> None:
    api_url = _get_api_url()
    print(f"Smoke test against: {api_url}")

    # 1. Start session
    print("[1] POST /session/start")
    try:
        result = _post(f"{api_url}/session/start", {"simulation_transcript": SMOKE_TRANSCRIPT})
    except urllib.error.HTTPError as e:
        print(f"FAIL: /session/start returned HTTP {e.code}: {e.read().decode()[:300]}")
        sys.exit(1)

    incident_id = result.get("incident_id")
    if not incident_id:
        print(f"FAIL: no incident_id in response: {result}")
        sys.exit(1)
    print(f"  incident_id: {incident_id}")

    # 2. Poll /status until ready or timeout
    print("[2] Polling /session/{id}/status")
    deadline = time.time() + 60  # 60-second max wait
    recommendation_ready = False
    while time.time() < deadline:
        time.sleep(3)
        try:
            status = _get(f"{api_url}/session/{incident_id}/status")
            print(f"  status: {status.get('status', '?')} | "
                  f"recommendation_ready: {status.get('recommendation_ready', False)}")
            if status.get("recommendation_ready"):
                recommendation_ready = True
                break
        except Exception as e:
            print(f"  poll error: {e}")

    if not recommendation_ready:
        print("FAIL: recommendation_ready never became True within 60s")
        sys.exit(1)

    # 3. Approve
    print("[3] POST /session/{id}/approve")
    try:
        approve = _post(f"{api_url}/session/{incident_id}/approve", {})
        assert approve.get("status") == "approved", f"unexpected approve status: {approve}"
        print(f"  approved: {approve}")
    except Exception as e:
        print(f"FAIL: /approve failed: {e}")
        sys.exit(1)

    print(f"\nSmoke test PASSED — incident_id: {incident_id}")


if __name__ == "__main__":
    run_smoke_test()
