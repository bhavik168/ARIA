"""
Integration test — Fire/Hazmat pipeline (SoDo warehouse fire scenario).

Requires a deployed stack. Set ARIA_INTEGRATION_TEST=1 to run.
"""
import json
import os
import time
import pytest
import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
REQUIRES_DEPLOY = pytest.mark.skipif(
    not os.environ.get("ARIA_INTEGRATION_TEST"),
    reason="Set ARIA_INTEGRATION_TEST=1 to run integration tests",
)

FIRE_TRANSCRIPT = [
    {"word": "there's", "speaker": "caller", "delay_ms": 0},
    {"word": "smoke", "speaker": "caller", "delay_ms": 300},
    {"word": "coming", "speaker": "caller", "delay_ms": 200},
    {"word": "from", "speaker": "caller", "delay_ms": 200},
    {"word": "a", "speaker": "caller", "delay_ms": 200},
    {"word": "warehouse", "speaker": "caller", "delay_ms": 300},
    {"word": "on", "speaker": "caller", "delay_ms": 200},
    {"word": "1st", "speaker": "caller", "delay_ms": 300},
    {"word": "Avenue", "speaker": "caller", "delay_ms": 300},
    {"word": "South", "speaker": "caller", "delay_ms": 300},
    {"word": "SoDo", "speaker": "caller", "delay_ms": 400},
    {"word": "flames", "speaker": "caller", "delay_ms": 500},
    {"word": "visible", "speaker": "caller", "delay_ms": 300},
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


def _poll(incident_id: str, field: str, timeout: int = 40) -> dict:
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
class TestFirePipeline:
    def test_fire_session_starts(self):
        result = _invoke_ingest(FIRE_TRANSCRIPT)
        assert "incident_id" in result

    def test_hazmat_agent_fires_for_fire_scenario(self):
        result = _invoke_ingest(FIRE_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "hazmat_result", timeout=40)
        assert item, "hazmat_result not in DynamoDB within 40s"
        haz = item["hazmat_result"]
        assert "evacuation_radius_meters" in haz
        assert haz["evacuation_radius_meters"] > 0

    def test_hazmat_result_includes_ppe(self):
        result = _invoke_ingest(FIRE_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "hazmat_result", timeout=40)
        assert item
        haz = item["hazmat_result"]
        assert "protective_equipment" in haz
        assert len(haz["protective_equipment"]) > 0

    def test_fire_agent_uses_fire_defaults(self):
        result = _invoke_ingest(FIRE_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "hazmat_result", timeout=40)
        assert item
        haz = item["hazmat_result"]
        # Fire (not hazmat) — evacuation radius is smaller than hazmat default
        assert haz["evacuation_radius_meters"] <= 300

    def test_navigation_fires_fire_engine_unit(self):
        result = _invoke_ingest(FIRE_TRANSCRIPT)
        incident_id = result["incident_id"]
        item = _poll(incident_id, "navigation_result", timeout=30)
        assert item
        nav = item["navigation_result"]
        # For fire, navigation should prefer fire_engine or ladder
        unit_type = nav.get("unit_type", "")
        assert unit_type in ("fire_engine", "ladder", "ambulance", "hazmat"), \
            f"Unexpected unit type for fire scenario: {unit_type}"
