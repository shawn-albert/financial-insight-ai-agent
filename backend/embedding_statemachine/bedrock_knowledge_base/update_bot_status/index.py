"""
Lambda function to update bot synchronization status.

This function updates the synchronization status of bots in DynamoDB,
handling both successful and failed states from various sources.
"""

import json
from typing import Any, Dict, Tuple

from app.repositories.common import _get_table_client
from app.repositories.custom_bot import compose_bot_id, decompose_bot_id
from app.routes.schemas.bot import type_sync_status
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from retry import retry
from shared.lambda_config import get_lambda_response, handle_lambda_error

logger = Logger()
tracer = Tracer()
metrics = Metrics()

RETRIES_TO_UPDATE_SYNC_STATUS = 4
RETRY_DELAY_TO_UPDATE_SYNC_STATUS = 2


@tracer.capture_method
@retry(tries=RETRIES_TO_UPDATE_SYNC_STATUS, delay=RETRY_DELAY_TO_UPDATE_SYNC_STATUS)
def update_sync_status(
    user_id: str,
    bot_id: str,
    sync_status: type_sync_status,
    sync_status_reason: str,
    last_exec_id: str,
) -> None:
    """
    Update bot sync status in DynamoDB with retry logic.

    Args:
        user_id: User identifier
        bot_id: Bot identifier
        sync_status: Current sync status
        sync_status_reason: Reason for status
        last_exec_id: Last execution identifier

    Raises:
        ClientError: If DynamoDB update fails after retries
    """
    table = _get_table_client(user_id)

    logger.info(
        "Updating sync status",
        extra={
            "user_id": user_id,
            "bot_id": bot_id,
            "sync_status": sync_status,
            "last_exec_id": last_exec_id,
        },
    )

    table.update_item(
        Key={"PK": user_id, "SK": compose_bot_id(user_id, bot_id)},
        UpdateExpression="SET SyncStatus = :sync_status, SyncStatusReason = :sync_status_reason, LastExecId = :last_exec_id",
        ExpressionAttributeValues={
            ":sync_status": sync_status,
            ":sync_status_reason": sync_status_reason,
            ":last_exec_id": last_exec_id,
        },
    )


@tracer.capture_method
def extract_from_cause(cause_str: str) -> Tuple[str, str, str]:
    """
    Extract PK, SK and build ARN from cause string.

    Args:
        cause_str: JSON string containing cause data

    Returns:
        Tuple containing PK, SK and build ARN

    Raises:
        ValueError: If required data is missing
        json.JSONDecodeError: If cause string is invalid JSON
    """
    cause = json.loads(cause_str)
    environment_variables = cause["Build"]["Environment"]["EnvironmentVariables"]

    pk = next(
        (item["Value"] for item in environment_variables if item["Name"] == "PK"), None
    )
    sk = next(
        (item["Value"] for item in environment_variables if item["Name"] == "SK"), None
    )

    if not pk or not sk:
        raise ValueError("PK or SK not found in cause")

    build_arn = cause["Build"].get("Arn", "")

    logger.debug(
        "Extracted cause data", extra={"pk": pk, "sk": sk, "build_arn": build_arn}
    )

    return pk, sk, build_arn


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics
@handle_lambda_error
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Handle bot status update requests from multiple sources.

    Supports updates from:
    - Direct status updates
    - Build failure causes
    - Ingestion job failures

    Args:
        event: Lambda event containing status update data
        context: Lambda context

    Returns:
        API Gateway compatible response

    Raises:
        ValueError: If required data is missing
        ClientError: If DynamoDB operations fail
    """
    cause = event.get("cause")
    ingestion_job = event.get("ingestion_job")

    if cause:
        pk, sk, build_arn = extract_from_cause(cause)
        sync_status = "FAILED"
        sync_status_reason = cause
        last_exec_id = build_arn
    elif ingestion_job:
        pk = event["pk"]
        sk = event["sk"]
        sync_status = "FAILED"
        sync_status_reason = str(ingestion_job["IngestionJob"]["FailureReasons"])
        last_exec_id = ingestion_job["IngestionJob"]["IngestionJobId"]
    else:
        pk = event["pk"]
        sk = event["sk"]
        sync_status = event["sync_status"]
        sync_status_reason = event.get("sync_status_reason", "")
        last_exec_id = event.get("last_exec_id", "")

    user_id = pk
    bot_id = decompose_bot_id(sk)

    logger.info(
        "Processing status update",
        extra={
            "user_id": user_id,
            "bot_id": bot_id,
            "sync_status": sync_status,
            "update_source": "cause"
            if cause
            else "ingestion"
            if ingestion_job
            else "direct",
        },
    )

    update_sync_status(user_id, bot_id, sync_status, sync_status_reason, last_exec_id)

    metrics.add_metric(
        name="BotStatusUpdated", unit=MetricUnit.Count, value=1, status=sync_status
    )

    return get_lambda_response(200, "Sync status updated successfully")
