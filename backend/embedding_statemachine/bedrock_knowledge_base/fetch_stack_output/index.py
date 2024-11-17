"""
Lambda function to fetch CloudFormation stack outputs.

This function retrieves CloudFormation stack outputs including knowledge base IDs,
data source IDs, and guardrail configurations for Bedrock chat bots.
"""

import os
from typing import Dict, List, TypedDict

import boto3
from app.repositories.custom_bot import decompose_bot_id
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from shared.lambda_config import handle_lambda_error

BEDROCK_REGION = os.environ["BEDROCK_REGION"]

logger = Logger()
tracer = Tracer()
metrics = Metrics()
cf_client = boto3.client("cloudformation", BEDROCK_REGION)


class StackOutput(TypedDict):
    """Type definition for stack output data."""

    KnowledgeBaseId: str
    DataSourceId: str
    GuardrailArn: str
    GuardrailVersion: str
    PK: str
    SK: str


@tracer.capture_method
def get_stack_outputs(stack_name: str) -> Dict[str, List[str]]:
    """
    Retrieve outputs from CloudFormation stack.

    Args:
        stack_name: Name of the CloudFormation stack

    Returns:
        Dictionary containing stack outputs

    Raises:
        ClientError: If stack outputs cannot be retrieved
    """
    response = cf_client.describe_stacks(StackName=stack_name)
    outputs = response["Stacks"][0]["Outputs"]

    return {
        "knowledge_base_id": next(
            (o["OutputValue"] for o in outputs if o["OutputKey"] == "KnowledgeBaseId"),
            None,
        ),
        "data_source_ids": [
            o["OutputValue"] for o in outputs if o["OutputKey"].startswith("DataSource")
        ],
        "guardrail_arn": next(
            (o["OutputValue"] for o in outputs if o["OutputKey"] == "GuardrailArn"),
            None,
        ),
        "guardrail_version": next(
            (o["OutputValue"] for o in outputs if o["OutputKey"] == "GuardrailVersion"),
            None,
        ),
    }


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics
@handle_lambda_error
def handler(event: Dict, context: LambdaContext) -> List[StackOutput]:
    """
    Handle requests to fetch CloudFormation stack outputs.

    Args:
        event: Lambda event containing PK and SK
        context: Lambda context

    Returns:
        List of stack outputs with knowledge base and data source IDs

    Raises:
        ClientError: If CloudFormation API calls fail
        ValueError: If stack outputs are invalid
    """
    pk = event["pk"]
    sk = event["sk"]
    bot_id = decompose_bot_id(sk)
    stack_name = f"BrChatKbStack{bot_id}"

    logger.info(
        "Fetching stack outputs", extra={"bot_id": bot_id, "stack_name": stack_name}
    )

    outputs = get_stack_outputs(stack_name)

    if not outputs["knowledge_base_id"] or not outputs["data_source_ids"]:
        raise ValueError("Required stack outputs missing")

    metrics.add_metric(name="StackOutputsFetched", unit=MetricUnit.Count, value=1)

    return [
        StackOutput(
            KnowledgeBaseId=outputs["knowledge_base_id"],
            DataSourceId=data_source_id,
            GuardrailArn=outputs["guardrail_arn"] or "",
            GuardrailVersion=outputs["guardrail_version"] or "",
            PK=pk,
            SK=sk,
        )
        for data_source_id in outputs["data_source_ids"]
    ]
