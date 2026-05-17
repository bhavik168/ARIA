#!/usr/bin/env python3
"""
Verify Provisioned Concurrency is working — no Lambda should cold start slowly.

Invokes each critical-path Lambda 20 times with no warm-up pause.
Asserts no invocation has an Init Duration > 200ms (cold start indicator).

Usage:
    python scripts/verify_cold_start.py

Requires:
    AWS credentials with Lambda:InvokeFunction permission
    Stack must be deployed with Provisioned Concurrency configured
"""
import boto3
import json
import os
import sys
import time

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNS = 20
COLD_START_THRESHOLD_MS = 200  # above this = cold start

CRITICAL_FUNCTIONS = [
    "aria-stream-processor",
    "aria-ingest",
    "aria-coordinator",
    "aria-navigation-tool",
    "aria-medical-tool",
]

MINIMAL_PAYLOADS = {
    "aria-stream-processor": {
        "incident_id": "verify-cold-start",
        "word": "test",
        "speaker": "caller",
        "context_so_far": "test",
    },
    "aria-ingest": {
        "httpMethod": "GET",
        "path": "/session/verify-cold-start/status",
        "pathParameters": {"id": "verify-cold-start"},
    },
    "aria-coordinator": {
        "incident_id": "verify-cold-start",
        "context_so_far": "test warmup ping",
        "trigger_reason": "warmup",
    },
    "aria-navigation-tool": {
        "incident_id": "verify-cold-start",
        "context_so_far": "warmup",
        "incident_data": {},
        "trigger_reason": "location_detected",
    },
    "aria-medical-tool": {
        "incident_id": "verify-cold-start",
        "context_so_far": "warmup",
        "incident_data": {},
    },
}

GREEN = "\033[92m"
RED   = "\033[91m"
YELLOW = "\033[93m"
BOLD  = "\033[1m"
DIM   = "\033[2m"
RESET = "\033[0m"


def _invoke(fn_name: str, payload: dict) -> dict:
    lam = boto3.client("lambda", region_name=REGION)
    t0 = time.time()
    resp = lam.invoke(
        FunctionName=fn_name,
        InvocationType="RequestResponse",
        LogType="Tail",
        Payload=json.dumps(payload).encode(),
    )
    elapsed_ms = int((time.time() - t0) * 1000)
    log_result = resp.get("LogResult", "")
    if log_result:
        import base64
        log_text = base64.b64decode(log_result).decode("utf-8", errors="replace")
    else:
        log_text = ""
    return {"elapsed_ms": elapsed_ms, "log": log_text}


def _extract_init_duration(log_text: str) -> float:
    """Extract Init Duration from Lambda log REPORT line if present."""
    for line in log_text.splitlines():
        if "Init Duration:" in line:
            for part in line.split("\t"):
                if "Init Duration:" in part:
                    try:
                        return float(part.replace("Init Duration:", "").replace("ms", "").strip())
                    except ValueError:
                        pass
    return 0.0


def verify_function(fn_name: str) -> bool:
    payload = MINIMAL_PAYLOADS.get(fn_name, {"warmup": True})
    cold_starts = []
    elapsed_times = []

    print(f"\n  {BOLD}{fn_name}{RESET}")
    for i in range(RUNS):
        result = _invoke(fn_name, payload)
        init_ms = _extract_init_duration(result["log"])
        elapsed_times.append(result["elapsed_ms"])
        if init_ms > COLD_START_THRESHOLD_MS:
            cold_starts.append((i + 1, init_ms))
            print(f"    Run {i+1:02d}: {result['elapsed_ms']:>5}ms  {RED}COLD START Init={init_ms:.0f}ms{RESET}")
        else:
            indicator = f"Init={init_ms:.0f}ms" if init_ms > 0 else "warm"
            print(f"    Run {i+1:02d}: {result['elapsed_ms']:>5}ms  {DIM}{indicator}{RESET}")

    avg_ms = sum(elapsed_times) / len(elapsed_times)
    if cold_starts:
        print(f"    {RED}✗ {len(cold_starts)}/{RUNS} cold starts detected{RESET}  avg={avg_ms:.0f}ms")
        return False
    else:
        print(f"    {GREEN}✓ No cold starts  avg={avg_ms:.0f}ms{RESET}")
        return True


def main():
    print(f"\n{BOLD}ARIA — Provisioned Concurrency Verification{RESET}")
    print(f"Invoking {RUNS} times per function. Cold start threshold: {COLD_START_THRESHOLD_MS}ms Init Duration\n")
    print(f"{DIM}{'─'*60}{RESET}")

    results = {}
    for fn_name in CRITICAL_FUNCTIONS:
        try:
            results[fn_name] = verify_function(fn_name)
        except Exception as e:
            print(f"  {RED}ERROR invoking {fn_name}: {e}{RESET}")
            results[fn_name] = False

    print(f"\n{DIM}{'─'*60}{RESET}")
    print(f"\n{BOLD}Summary:{RESET}")
    all_pass = True
    for fn_name, passed in results.items():
        status = f"{GREEN}✓ PASS{RESET}" if passed else f"{RED}✗ FAIL{RESET}"
        print(f"  {status}  {fn_name}")
        if not passed:
            all_pass = False

    if all_pass:
        print(f"\n{GREEN}{BOLD}All functions warm — Provisioned Concurrency confirmed working.{RESET}\n")
        sys.exit(0)
    else:
        print(f"\n{RED}{BOLD}Cold starts detected. Check Provisioned Concurrency configuration in CDK.{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
