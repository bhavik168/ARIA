"""
Integration test — Medical pipeline (cardiac arrest scenario).

Requires a deployed stack. Set ARIA_API_URL or AWS credentials to AriaStack.
Run with: pytest tests/integration/ -v -s
Skip with: pytest tests/unit/ (unit tests don't need a deployed stack)
"""
import json
import os
import time
import pytest
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
REQUIRES_DEPLOY = pytest.mark.skipif(
    not os.environ.get("ARIA_INTEGRATION_TEST"),
    reason="Set ARIA_INTEGRATION_TEST=1 and deploy the stack to run integration tests",
)

CARDIAC_TRANSCRIPT = [
    {"word": "my", "speaker": "caller", "delay_ms": 0},
    {"word": "husband", "speaker": "caller", "delay_ms": 300},
    {"word": "collapsed", "speaker": "caller", "delay_ms": 300},
    {"word": "he's", "speaker": "caller", "delay_ms": 300},
    {"word": "not", "speaker": "caller", "delay_ms": 200},
    {"word": "breathing", "speaker": "caller", "delay_ms": 200},
    {"word": "1420", "speaker": "caller", "delay_ms": 500},
    {"word": "East", "speaker": "caller", "delay_ms": 300},
    {"word": "Pike", "speaker": "caller", "delay_ms": 300},
    {"word": "Street", "speaker": "caller", "delay_ms": 300},
]


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
    result = json.loads(resp["Payload"].read())
    body = json.loads(result.get("body", "{}")) if isinstance(result.get("body"), str) else result
    return body


def _poll(incident_id: str, field: str, timeout: int = 45) -> dict:
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table("aria-incidents")
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = table.get_item(Key={"incident_id": incident_id, "timestamp": "latest"})
        item = resp.get("Item", {})
        if item.get(field):
            return item
        time.sleep(2)
    return {}


@REQUIRES_DEPLOY
class TestMedicalPipeline:
    def test_session_starts_and_returns_incident_id(self):
        result = _invoke_ingest(CARDIAC_TRANSCRIPT)
        assert "incident_id" in result, f"no incident_id in: {result}"
        assert len(result["incident_id"]) > 5

    def test_navigation_agent_fires_and_returns_unit(self):
        result = _invoke_ingest(CARDIAC_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "navigation_result", timeout=30)
        assert item, "navigation_result never appeared in DynamoDB within 30s"
        nav = item["navigation_result"]
        assert "unit_id" in nav
        assert "eta_minutes" in nav
        assert nav["eta_minutes"] > 0

    def test_medical_agent_fires_and_returns_hospital(self):
        result = _invoke_ingest(CARDIAC_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "medical_result", timeout=40)
        assert item, "medical_result never appeared in DynamoDB within 40s"
        med = item["medical_result"]
        assert "recommended_hospital" in med
        hosp = med["recommended_hospital"]
        assert "name" in hosp
        assert "eta_minutes" in hosp
        assert "er_status" in hosp

    def test_medical_agent_includes_triage_protocol(self):
        result = _invoke_ingest(CARDIAC_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "medical_result", timeout=40)
        assert item
        med = item["medical_result"]
        assert "triage_protocol" in med
        assert len(med["triage_protocol"]) > 10

    def test_coordinator_produces_recommendation_card(self):
        result = _invoke_ingest(CARDIAC_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "recommendation_ready", timeout=60)
        assert item.get("recommendation_ready"), "recommendation_ready never set"

    def test_pipeline_completes_within_latency_budget(self):
        t0 = time.time()
        result = _invoke_ingest(CARDIAC_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "recommendation_ready", timeout=20)
        elapsed = time.time() - t0
        assert item.get("recommendation_ready"), "recommendation_ready not set within 20s"
        assert elapsed < 20, f"Pipeline took {elapsed:.1f}s — exceeds 20s budget"
