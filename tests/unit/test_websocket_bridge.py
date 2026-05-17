"""Unit tests for shared WebSocket push utility."""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest
from moto import mock_aws
import boto3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend/shared/utils"))


@pytest.fixture(autouse=True)
def aws_mock():
    with mock_aws():
        yield


@pytest.fixture
def connections_table():
    ddb = boto3.resource("dynamodb", region_name="us-east-1")
    table = ddb.create_table(
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
    return table


def _import_module():
    if "websocket" in sys.modules:
        del sys.modules["websocket"]
    import websocket
    return websocket


class TestPushEventNoEndpoint:
    def test_push_event_noop_when_no_endpoint(self, connections_table):
        """push_event silently returns when WS_ENDPOINT is not configured."""
        ws_module = _import_module()
        # WS_ENDPOINT is "" (default) — should not raise
        ws_module.push_event("test-incident", "transcript_update", {"word": "hello"})

    def test_push_event_does_not_crash_without_connections(self, connections_table):
        ws_module = _import_module()
        # No connections in the table for this incident
        with patch.dict(os.environ, {"WS_ENDPOINT": "wss://test.execute-api.us-east-1.amazonaws.com/prod"}):
            ws_module._apigw_client = None  # reset cached client
            # _get_connections returns [] — no error
            conns = ws_module._get_connections("unknown-incident")
            assert conns == []


class TestConnectionManagement:
    def test_get_connections_returns_empty_for_unknown_incident(self, connections_table):
        ws_module = _import_module()
        conns = ws_module._get_connections("no-such-incident")
        assert conns == []

    def test_get_connections_returns_matching_connections(self, connections_table):
        connections_table.put_item(Item={
            "connection_id": "conn-abc",
            "incident_id": "test-incident-001",
            "ttl": 9999999999,
        })
        ws_module = _import_module()
        conns = ws_module._get_connections("test-incident-001")
        assert len(conns) == 1
        assert conns[0]["connection_id"] == "conn-abc"

    def test_remove_connection_deletes_item(self, connections_table):
        connections_table.put_item(Item={
            "connection_id": "stale-conn",
            "incident_id": "some-incident",
        })
        ws_module = _import_module()
        ws_module._remove_connection("stale-conn")

        item = connections_table.get_item(Key={"connection_id": "stale-conn"}).get("Item")
        assert item is None

    def test_get_connections_does_not_return_other_incidents(self, connections_table):
        connections_table.put_item(Item={
            "connection_id": "conn-1",
            "incident_id": "incident-A",
        })
        connections_table.put_item(Item={
            "connection_id": "conn-2",
            "incident_id": "incident-B",
        })
        ws_module = _import_module()
        conns = ws_module._get_connections("incident-A")
        ids = [c["connection_id"] for c in conns]
        assert "conn-1" in ids
        assert "conn-2" not in ids


class TestPushEventWithMockedClient:
    def test_push_event_calls_post_to_connection(self, connections_table):
        connections_table.put_item(Item={
            "connection_id": "conn-xyz",
            "incident_id": "my-incident",
        })
        ws_module = _import_module()

        mock_client = MagicMock()
        ws_module._apigw_client = mock_client

        with patch.dict(os.environ, {"WS_ENDPOINT": "wss://test.execute-api.us-east-1.amazonaws.com/prod"}):
            ws_module.push_event("my-incident", "agent_complete", {"agent": "navigation"})

        mock_client.post_to_connection.assert_called_once()
        call_kwargs = mock_client.post_to_connection.call_args
        assert call_kwargs.kwargs["ConnectionId"] == "conn-xyz"

    def test_push_event_removes_stale_gone_connection(self, connections_table):
        connections_table.put_item(Item={
            "connection_id": "gone-conn",
            "incident_id": "my-incident",
        })
        ws_module = _import_module()

        mock_client = MagicMock()
        # Simulate GoneException on post_to_connection
        gone_exception = type("GoneException", (Exception,), {})
        mock_client.exceptions.GoneException = gone_exception
        mock_client.post_to_connection.side_effect = gone_exception("Connection gone")
        ws_module._apigw_client = mock_client

        with patch.dict(os.environ, {"WS_ENDPOINT": "wss://test.execute-api.us-east-1.amazonaws.com/prod"}):
            ws_module.push_event("my-incident", "transcript_update", {"word": "test"})

        # Connection should have been removed from DynamoDB
        item = connections_table.get_item(Key={"connection_id": "gone-conn"}).get("Item")
        assert item is None
