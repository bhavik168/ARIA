import os
import boto3
from aws_lambda_powertools import Logger

logger = Logger()

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_DEPLOY_REGION"])
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]


@logger.inject_lambda_context
def lambda_handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    table = dynamodb.Table(CONNECTIONS_TABLE)
    table.delete_item(Key={"connection_id": connection_id})
    logger.info("WebSocket disconnected", extra={"connection_id": connection_id})
    return {"statusCode": 200, "body": "Disconnected"}
