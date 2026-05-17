import json
from aws_lambda_powertools import Logger

logger = Logger()


@logger.inject_lambda_context
def lambda_handler(event, context):
    # $default route — handles keepalive pings and unknown actions without closing the connection.
    action = ""
    try:
        body = json.loads(event.get("body") or "{}")
        action = body.get("action", "")
    except (json.JSONDecodeError, TypeError):
        pass
    logger.debug("ws $default", extra={"action": action})
    return {"statusCode": 200, "body": "ok"}
