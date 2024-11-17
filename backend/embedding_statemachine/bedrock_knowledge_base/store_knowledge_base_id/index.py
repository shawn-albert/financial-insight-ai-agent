"""
Lambda function to store knowledge base IDs in DynamoDB.

This function stores Bedrock knowledge base and data source IDs
in DynamoDB for bot configurations.
"""

from typing import Dict, List, TypedDict

from app.repositories.custom_bot import decompose_bot_id, update_knowledge_base_id
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from shared.lambda_config import handle_lambda_error

logger = Logger()
tracer = Tracer()
metrics = Metrics()


class StackOutput(TypedDict):
    """Type definition for stack output data."""

    KnowledgeBaseId: str
    DataSourceId: str


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics
@handle_lambda_error
def handler(event: Dict, context: LambdaContext) -> None:
    """
    Store knowledge base and data source IDs in DynamoDB.

    Args:
        event: Lambda event containing stack outputs and identifiers
        context: Lambda context

    Raises:
        ValueError: If required data is missing
        ClientError: If DynamoDB operations fail
    """
    pk = event["pk"]
    sk = event["sk"]
    stack_output: List[StackOutput] = event["stack_output"]

    if not stack_output:
        raise ValueError("Stack output is empty")

    kb_id = stack_output[0]["KnowledgeBaseId"]
    data_source_ids = [x["DataSourceId"] for x in stack_output]

    user_id = pk
    bot_id = decompose_bot_id(sk)

    logger.info(
        "Storing knowledge base configuration",
        extra={
            "user_id": user_id,
            "bot_id": bot_id,
            "knowledge_base_id": kb_id,
            "data_source_count": len(data_source_ids),
        },
    )

    update_knowledge_base_id(user_id, bot_id, kb_id, data_source_ids)

    metrics.add_metric(name="KnowledgeBaseStored", unit=MetricUnit.Count, value=1)
