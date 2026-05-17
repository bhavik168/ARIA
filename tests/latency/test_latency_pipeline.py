"""
Latency regression tests — runs full pipeline N times and asserts P50/P95 against hard ceilings.

Requires a deployed stack. Set ARIA_LATENCY_TEST=1 to run.
Run with: pytest tests/latency/ -v -s

Hard ceilings (from PLAN.md):
  navigation_agent_complete_ms  P95 < 10,000ms
  medical_agent_complete_ms     P95 < 12,000ms
  coordinator_card_complete_ms  P95 < 15,000ms
"""
import json
import os
import statistics
import time
import pytest
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
RUNS = int(os.environ.get("LATENCY_RUNS", "5"))

REQUIRES_LATENCY = pytest.mark.skipif(
    not os.environ.get("ARIA_LATENCY_TEST"),
    reason="Set ARIA_LATENCY_TEST=1 to run latency tests (requires deployed stack)",
)

TRANSCRIPT = [
    {"word": "my", "speaker": "caller", "delay_ms": 0},
    {"word": "husband", "speaker": "caller", "delay_ms": 300},
    {"word": "not", "speaker": "caller", "delay_ms": 300},
    {"word": "breathing", "speaker": "caller", "delay_ms": 200},
    {"word": "1420", "speaker": "caller", "delay_ms": 400},
    {"word": "East", "speaker": "caller", "delay_ms": 300},
    {"word": "Pike", "speaker": "caller", "delay_ms": 200},
    {"word": "Street", "speaker": "caller", "delay_ms": 200},
]


def _start_session() -> tuple[str, int]:
    lam = boto3.client("lambda", region_name=REGION)
    t0 = int(time.time() * 1000)
    resp = lam.invoke(
        FunctionName="aria-ingest",
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "httpMethod": "POST",
            "path": "/session/start",
            "body": json.dumps({"simulation_transcript": TRANSCRIPT}),
        }).encode(),
    )
    result = json.loads(resp["Payload"].read())
    body = json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result
    incident_id = body.get("incident_id", "")
    return incident_id, t0


def _poll_until(incident_id: str, field: str, t0: int, timeout_ms: int) -> int:
    """Returns elapsed_ms from t0 to when field appears. Returns timeout_ms if not found."""
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table("aria-incidents")
    deadline = time.time() + (timeout_ms / 1000)
    while time.time() < deadline:
        resp = table.get_item(Key={"incident_id": incident_id, "timestamp": "latest"})
        item = resp.get("Item", {})
        if item.get(field):
            return int(time.time() * 1000) - t0
        time.sleep(0.5)
    return timeout_ms  # timed out


def _percentile(data: list, p: int) -> float:
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * p / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


@REQUIRES_LATENCY
class TestLatencyPipeline:
    def test_navigation_p95_under_10s(self):
        times = []
        for i in range(RUNS):
            incident_id, t0 = _start_session()
            elapsed = _poll_until(incident_id, "navigation_result", t0, timeout_ms=15000)
            times.append(elapsed)
            print(f"  Run {i+1}: navigation={elapsed}ms")
            time.sleep(2)  # brief pause between runs

        p50 = _percentile(times, 50)
        p95 = _percentile(times, 95)
        print(f"\n  navigation_agent_complete_ms  P50={p50}ms  P95={p95}ms")
        assert p95 < 10_000, f"Navigation P95 {p95}ms exceeds 10,000ms ceiling"

    def test_medical_p95_under_12s(self):
        times = []
        for i in range(RUNS):
            incident_id, t0 = _start_session()
            elapsed = _poll_until(incident_id, "medical_result", t0, timeout_ms=18000)
            times.append(elapsed)
            print(f"  Run {i+1}: medical={elapsed}ms")
            time.sleep(2)

        p95 = _percentile(times, 95)
        print(f"\n  medical_agent_complete_ms  P95={p95}ms")
        assert p95 < 12_000, f"Medical P95 {p95}ms exceeds 12,000ms ceiling"

    def test_coordinator_card_p95_under_15s(self):
        times = []
        for i in range(RUNS):
            incident_id, t0 = _start_session()
            elapsed = _poll_until(incident_id, "recommendation_ready", t0, timeout_ms=20000)
            times.append(elapsed)
            print(f"  Run {i+1}: coordinator={elapsed}ms")
            time.sleep(2)

        p50 = _percentile(times, 50)
        p95 = _percentile(times, 95)
        print(f"\n  coordinator_card_complete_ms  P50={p50}ms  P95={p95}ms")
        assert p95 < 15_000, f"Coordinator P95 {p95}ms exceeds 15,000ms ceiling"

    def test_print_latency_summary(self):
        """Full latency summary table — run once, print all metrics."""
        nav_times, med_times, card_times = [], [], []

        for i in range(RUNS):
            incident_id, t0 = _start_session()

            nav_ms = _poll_until(incident_id, "navigation_result", t0, 15000)
            nav_times.append(nav_ms)

            med_ms = _poll_until(incident_id, "medical_result", t0, 18000)
            med_times.append(med_ms)

            card_ms = _poll_until(incident_id, "recommendation_ready", t0, 22000)
            card_times.append(card_ms)

            print(f"  Run {i+1}: nav={nav_ms}ms  med={med_ms}ms  card={card_ms}ms")
            time.sleep(3)

        print(f"\n{'─'*60}")
        print(f"  {'Metric':<35} {'P50':>8} {'P95':>8}")
        print(f"{'─'*60}")
        print(f"  {'navigation_agent_complete_ms':<35} {_percentile(nav_times,50):>8.0f} {_percentile(nav_times,95):>8.0f}")
        print(f"  {'medical_agent_complete_ms':<35} {_percentile(med_times,50):>8.0f} {_percentile(med_times,95):>8.0f}")
        print(f"  {'coordinator_card_complete_ms':<35} {_percentile(card_times,50):>8.0f} {_percentile(card_times,95):>8.0f}")
        print(f"{'─'*60}")
        print(f"  Hard ceilings: nav<10000  med<12000  card<15000")
