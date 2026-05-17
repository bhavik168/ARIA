"""
Shared WebSocket push utility — used by all Lambda functions that emit dashboard events.

Usage:
    from backend.shared.utils.websocket import push_event
    push_event(incident_id, "agent_complete", {"agent": "navigation", ...})
"""
import json
import os
import boto3
from aws_lambda_powertools import Logger

logger = Logger()

_apigw_client = None
_dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_DEPLOY_REGION", "us-east-1"))
CONNECTIONS_TABLE = os.environ.get("CONNECTIONS_TABLE", "aria-ws-connections")


def push_event(incident_id: str, event_type: str, payload: dict) -> None:
    """Push an event to all WebSocket connections subscribed to this incident."""
    ws_endpoint = os.environ.get("WS_ENDPOINT", "")
    if not ws_endpoint:
        return

    client = _get_apigw_client(ws_endpoint)
    connections = _get_connections(incident_id)
    data = json.dumps({"type": event_type, **payload}).encode()

    stale_connections = []
    for conn in connections:
        connection_id = conn["connection_id"]
        try:
            client.post_to_connection(ConnectionId=connection_id, Data=data)
        except client.exceptions.GoneException:
            stale_connections.append(connection_id)
        except Exception as e:
            logger.warning(f"Failed to push to {connection_id}", exc_info=e)

    for cid in stale_connections:
        _remove_connection(cid)


def _get_apigw_client(ws_endpoint: str):
    global _apigw_client
    if _apigw_client is None:
        endpoint = ws_endpoint.replace("wss://", "https://")
        _apigw_client = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=endpoint,
            region_name=os.environ.get("AWS_DEPLOY_REGION", "us-east-1"),
        )
    return _apigw_client


def _get_connections(incident_id: str) -> list:
    table = _dynamodb.Table(CONNECTIONS_TABLE)
    try:
        resp = table.query(
            IndexName="incident-index",
            KeyConditionExpression="incident_id = :iid",
            ExpressionAttributeValues={":iid": incident_id},
        )
        return resp.get("Items", [])
    except Exception as e:
        logger.error("Failed to query connections", exc_info=e)
        return []


def _remove_connection(connection_id: str) -> None:
    table = _dynamodb.Table(CONNECTIONS_TABLE)
    try:
        table.delete_item(Key={"connection_id": connection_id})
    except Exception:
        pass
