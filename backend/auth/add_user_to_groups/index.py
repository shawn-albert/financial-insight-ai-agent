"""
Lambda handler for adding users to Cognito groups.

This module handles Cognito post-confirmation and post-authentication events,
automatically adding users to specified groups based on trigger conditions.
"""

import json
import os
from typing import Any, Dict, List

import boto3
from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

USER_POOL_ID: str = os.environ["USER_POOL_ID"]
AUTO_JOIN_USER_GROUPS: List[str] = json.loads(
    os.environ.get("AUTO_JOIN_USER_GROUPS", "[]")
)

logger = Logger()
tracer = Tracer()
metrics = Metrics()

cognito = boto3.client("cognito-idp")


def add_user_to_groups(user_pool_id: str, username: str, groups: List[str]) -> None:
    """
    Add a user to multiple Cognito user groups.

    Args:
        user_pool_id: The ID of the Cognito user pool
        username: The username of the user to add
        groups: List of group names to add the user to

    Raises:
        ClientError: If there is an error adding user to groups
    """
    for group in groups:
        try:
            logger.info(
                "Adding user to group",
                extra={
                    "user_pool_id": user_pool_id,
                    "username": username,
                    "group": group,
                },
            )
            cognito.admin_add_user_to_group(
                UserPoolId=user_pool_id,
                Username=username,
                GroupName=group,
            )
            metrics.add_metric(
                name="GroupAddSuccess",
                unit=MetricUnit.Count,
                value=1,
                group_name=group,
            )
        except ClientError as e:
            logger.error(
                "Failed to add user to group",
                extra={
                    "error_code": e.response["Error"]["Code"],
                    "error_message": e.response["Error"]["Message"],
                    "user_pool_id": user_pool_id,
                    "username": username,
                    "group": group,
                },
            )
            metrics.add_metric(
                name="GroupAddFailure",
                unit=MetricUnit.Count,
                value=1,
                group_name=group,
            )
            raise


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Handle Cognito post-confirmation and post-authentication events.

    This function processes two types of Cognito triggers:
    1. PostConfirmation_ConfirmSignUp: When a user confirms their signup
    2. PostAuthentication_Authentication: When a user authenticates and needs password change

    Args:
        event: Cognito trigger event containing user and request details
        context: Lambda execution context

    Returns:
        Dict containing the original event data

    Raises:
        Exception: If user group assignment fails
    """
    try:
        user_name: str = event["userName"]
        user_attributes: Dict[str, str] = event["request"]["userAttributes"]
        trigger_source: str = event["triggerSource"]

        logger.info(
            "Processing Cognito trigger",
            extra={
                "trigger_source": trigger_source,
                "username": user_name,
                "user_status": user_attributes.get("cognito:user_status"),
            },
        )

        if trigger_source == "PostConfirmation_ConfirmSignUp":
            add_user_to_groups(USER_POOL_ID, user_name, AUTO_JOIN_USER_GROUPS)
            metrics.add_metric(
                name="PostConfirmationTrigger", unit=MetricUnit.Count, value=1
            )

        elif trigger_source == "PostAuthentication_Authentication":
            user_status: str = user_attributes["cognito:user_status"]
            if user_status == "FORCE_CHANGE_PASSWORD":
                add_user_to_groups(USER_POOL_ID, user_name, AUTO_JOIN_USER_GROUPS)
                metrics.add_metric(
                    name="PostAuthenticationTrigger", unit=MetricUnit.Count, value=1
                )

        return event

    except Exception as e:
        logger.exception(
            "Failed to process Cognito trigger",
            extra={
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise
