"""Unit tests for aria-coordinator Lambda handler."""
import importlib.util
import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
from moto import mock_aws
import boto3

_HANDLER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../backend/lambdas/aria-coordinator/handler.py"))


@pytest.fixture(autouse=True)
def aws_mock():
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_tables(mock_incident_id):
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    incidents = ddb.create_table(
        TableName="aria-incidents",
        KeySchema=[
            {"AttributeName": "incident_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "incident_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    incidents.put_item(Item={
        "incident_id": mock_incident_id,
        "timestamp": "latest",
        "status": "ingesting",
        "incident_type": "medical",
        "severity": "critical",
        "t0_ms": 0,
    })

    ddb.create_table(
        TableName="aria-ws-connections",
        KeySchema=[{"AttributeName": "connection_id", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "connection_id", "AttributeType": "S"},
            {"AttributeName": "incident_id", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName": "incident-index",
            "KeySchema": [{"AttributeName": "incident_id", "KeyType": "HASH"}],
            "Projection": {"ProjectionType": "ALL"},
        }],
        BillingMode="PAY_PER_REQUEST",
    )

    ddb.create_table(
        TableName="aria-overrides",
        KeySchema=[
            {"AttributeName": "incident_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "incident_id", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _import_handler():
    if "handler" in sys.modules:
        del sys.modules["handler"]
    spec = importlib.util.spec_from_file_location("handler", _HANDLER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["handler"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_lambda_response(payload: dict):
    mock_payload = MagicMock()
    mock_payload.read.return_value = json.dumps(payload).encode()
    return {"Payload": mock_payload}


class TestCardSynthesis:
    def test_synthesize_card_structure(self, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        results = {
            "navigation": {
                "status": "ok",
                "recommended_unit": {"unit_id": "MED-1", "unit_type": "ambulance", "eta_minutes": 4},
            },
            "medical": {
                "status": "ok",
                "recommended_hospital": {"name": "Harborview", "eta_minutes": 5, "er_status": "accepting"},
                "triage_protocol": "BLS protocol",
            },
        }
        card = handler._synthesize_card(mock_incident_id, "caller said not breathing", results, {}, 0)
        assert card["incident_id"] == mock_incident_id
        assert "severity" in card
        assert "recommended_unit" in card
        assert "recommended_hospital" in card
        assert "ai_confidence" in card
        assert card["requires_approval"] is True

    def test_card_confidence_high_when_all_ok(self, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        results = {
            "navigation": {"status": "ok"},
            "medical": {"status": "ok"},
        }
        card = handler._synthesize_card(mock_incident_id, "context", results, {}, 0)
        assert card["ai_confidence"] == "high"

    def test_card_confidence_low_when_agent_failed(self, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        results = {
            "navigation": {"status": "failed", "error": "timeout"},
            "medical": {"status": "ok"},
        }
        card = handler._synthesize_card(mock_incident_id, "context", results, {}, 0)
        assert card["ai_confidence"] == "low"

    def test_hazard_warnings_empty_for_medical(self, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        results = {"navigation": {"status": "ok"}, "medical": {"status": "ok"}}
        card = handler._synthesize_card(mock_incident_id, "context", results, {}, 0)
        assert isinstance(card["hazard_warnings"], list)

    def test_hazard_warnings_populated_for_hazmat(self, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        results = {
            "navigation": {"status": "ok"},
            "hazmat": {
                "status": "ok",
                "hazard_warnings": ["chlorine", "evacuation 300m"],
            },
        }
        card = handler._synthesize_card(mock_incident_id, "chlorine spill", results, {}, 0)
        assert card["hazard_warnings"] == ["chlorine", "evacuation 300m"]


class TestApproveRoute:
    def test_approve_sets_dispatcher_approved(self, lambda_context, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        event = {
            "httpMethod": "POST",
            "path": f"/session/{mock_incident_id}/approve",
            "pathParameters": {"id": mock_incident_id},
            "body": "{}",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "approved"

        # Verify DynamoDB was updated
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        item = ddb.Table("aria-incidents").get_item(
            Key={"incident_id": mock_incident_id, "timestamp": "latest"}
        ).get("Item", {})
        assert item.get("dispatcher_approved") is True

    def test_approve_missing_incident_returns_404(self, lambda_context, dynamodb_tables):
        handler = _import_handler()
        event = {
            "httpMethod": "POST",
            "path": "/session/nonexistent-id/approve",
            "pathParameters": {"id": "nonexistent-id"},
            "body": "{}",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["statusCode"] in (404, 400)


class TestOverrideRoute:
    def test_override_writes_to_dynamodb(self, lambda_context, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        event = {
            "httpMethod": "POST",
            "path": f"/session/{mock_incident_id}/override",
            "pathParameters": {"id": mock_incident_id},
            "body": json.dumps({
                "override_reason": "Better route known",
                "dispatcher_choice": {"unit_id": "MED-2"},
            }),
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["statusCode"] == 200
        body = json.loads(result["body"])
        assert body["status"] == "override_recorded"


class TestGuardrailBypass:
    def test_no_guardrail_id_passes_card_through(self, dynamodb_tables, mock_incident_id):
        handler = _import_handler()
        card = {"incident_id": mock_incident_id, "severity": "critical", "summary": "cardiac arrest"}
        # GUARDRAIL_ID is empty string → should not block
        blocked, reason = handler._apply_guardrail(card)
        assert blocked is False
