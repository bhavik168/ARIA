import json
import os
import time
import boto3
from aws_lambda_powertools import Logger

logger = Logger()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]


@logger.inject_lambda_context
def lambda_handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    query_params = event.get("queryStringParameters") or {}
    incident_id = query_params.get("incident_id", "")

    table = dynamodb.Table(CONNECTIONS_TABLE)
    table.put_item(Item={
        "connection_id": connection_id,
        "incident_id": incident_id,
        "connected_at": int(time.time()),
        "ttl": int(time.time()) + 7200,  # 2-hour TTL
    })

    logger.info("WebSocket connected", extra={"connection_id": connection_id, "incident_id": incident_id})
    return {"statusCode": 200, "body": "Connected"}
