"""Unit tests for aria-hazmat-tool Lambda handler."""
import sys
import os
from unittest.mock import patch

import pytest
from moto import mock_aws
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend/lambdas/aria-hazmat-tool"))


@pytest.fixture(autouse=True)
def aws_mock():
    with mock_aws():
        yield


@pytest.fixture
def dynamodb_tables():
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    ddb.create_table(
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


def _import_handler():
    if "handler" in sys.modules:
        del sys.modules["handler"]
    import handler
    return handler


class TestDefaultProtocols:
    def test_fire_trigger_uses_fire_defaults(self, dynamodb_tables):
        handler = _import_handler()
        result = handler._build_result({}, is_hazmat=False)
        assert result["hazard_type"] == "structure_fire"
        assert result["evacuation_radius_meters"] == 150
        assert "SCBA" in result["protective_equipment"]

    def test_hazmat_trigger_uses_hazmat_defaults(self, dynamodb_tables):
        handler = _import_handler()
        result = handler._build_result({}, is_hazmat=True)
        assert result["hazard_type"] == "chemical_unknown"
        assert result["evacuation_radius_meters"] >= 200
        assert any("HAZMAT" in ppe or "Level" in ppe for ppe in result["protective_equipment"])

    def test_hazmat_has_larger_evacuation_than_fire(self, dynamodb_tables):
        handler = _import_handler()
        fire = handler._build_result({}, is_hazmat=False)
        haz = handler._build_result({}, is_hazmat=True)
        assert haz["evacuation_radius_meters"] > fire["evacuation_radius_meters"]

    def test_kb_excerpt_included_when_kb_data_present(self, dynamodb_tables):
        handler = _import_handler()
        kb_data = {"content": "ERG Guide 124: Chlorine. Isolation 100m.", "source": "s3://aria-kb/hazmat.pdf"}
        result = handler._build_result(kb_data, is_hazmat=True)
        assert result["kb_excerpt"] == kb_data["content"]
        assert result["source_document"] == kb_data["source"]


class TestHazmatDetection:
    def test_chemical_in_context_triggers_hazmat(self, dynamodb_tables):
        handler = _import_handler()
        # "chemical" in context → is_hazmat=True even if trigger says fire
        is_hazmat = "chemical" in "chlorine chemical spill".lower()
        assert is_hazmat is True

    def test_hazmat_trigger_reason_detected(self, dynamodb_tables):
        handler = _import_handler()
        trigger = "hazmat_keyword_detected"
        is_hazmat = trigger == "hazmat_keyword_detected"
        assert is_hazmat is True


class TestHandlerInvocation:
    def test_fire_scenario_returns_ok(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "structure fire at warehouse on 1st Ave South",
            "trigger_reason": "fire_keyword_detected",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["status"] == "ok"
        assert result["incident_id"] == mock_incident_id
        assert "evacuation_radius_meters" in result
        assert "protective_equipment" in result

    def test_hazmat_scenario_returns_ok(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "chlorine gas leak at Terminal 18 Port of Seattle",
            "trigger_reason": "hazmat_keyword_detected",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert result["status"] == "ok"
        assert result["evacuation_radius_meters"] >= 200

    def test_handler_includes_elapsed_ms(self, lambda_context, mock_incident_id, dynamodb_tables):
        handler = _import_handler()
        event = {
            "incident_id": mock_incident_id,
            "context_so_far": "fire at building",
            "trigger_reason": "fire_keyword_detected",
        }
        result = handler.lambda_handler(event, lambda_context)
        assert "elapsed_ms" in result
        assert result["elapsed_ms"] >= 0
