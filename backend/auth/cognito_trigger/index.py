"""
Lambda handler for Cognito Trigger custom resource.

This module implements the Lambda function that handles the creation, update,
and deletion of Cognito User Pool triggers through CloudFormation custom resources.
"""

import json
import os
from typing import Dict

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.data_classes import (
    CloudFormationCustomResourceEvent,
    event_source,
)
from aws_lambda_powertools.utilities.typing import LambdaContext
from botocore.exceptions import ClientError

USER_POOL_ID = os.environ["USER_POOL_ID"]

cognito = boto3.client("cognito-idp")
logger = Logger()
tracer = Tracer()


@tracer.capture_method
def update_user_pool_lambda_config(
    user_pool_id: str, attr: Dict, lambda_config: Dict
) -> None:
    """
    Updates the Lambda configuration of a Cognito user pool.

    Args:
        user_pool_id: The ID of the Cognito user pool
        attr: The user pool attributes
        lambda_config: The Lambda configuration containing the triggers
    """
    logger.info(
        "Starting user pool update",
        extra={
            "user_pool_id": user_pool_id,
            "current_lambda_config": json.dumps(attr.get("LambdaConfig", {})),
            "new_lambda_config": json.dumps(lambda_config),
        },
    )

    valid_attributes = [
        "Policies",
        "AutoVerifiedAttributes",
        "SmsVerificationMessage",
        "EmailVerificationMessage",
        "EmailVerificationSubject",
        "VerificationMessageTemplate",
        "SmsAuthenticationMessage",
        "UserAttributeUpdateSettings",
        "MfaConfiguration",
        "DeviceConfiguration",
        "EmailConfiguration",
        "SmsConfiguration",
        "UserPoolTags",
        "AdminCreateUserConfig",
        "UserPoolAddOns",
        "AccountRecoverySetting",
    ]

    update_params = {k: v for k, v in attr.items() if k in valid_attributes}

    logger.info(
        "Prepared update parameters",
        extra={
            "update_params": json.dumps(update_params),
            "final_lambda_config": json.dumps(lambda_config),
        },
    )

    response = cognito.update_user_pool(
        UserPoolId=user_pool_id,
        **update_params,
        LambdaConfig=lambda_config,
    )

    logger.info(
        "User pool update completed",
        extra={
            "response": json.dumps(response),
        },
    )


@tracer.capture_method
def on_create(event: CloudFormationCustomResourceEvent) -> Dict:
    """
    Handle Create event for the custom resource.

    Args:
        event: CloudFormation custom resource event

    Returns:
        Dict containing physical ID and resource data
    """
    logger.info("Handling Create request")
    response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
    attr = response["UserPool"]
    lambda_config = attr.get("LambdaConfig", {})
    triggers = event.resource_properties["Triggers"]

    update_user_pool_lambda_config(
        USER_POOL_ID,
        attr,
        lambda_config={**lambda_config, **triggers},
    )

    return {
        "PhysicalResourceId": f"{USER_POOL_ID}-triggers",
        "Data": event.resource_properties,
    }


@tracer.capture_method
def on_update(event: CloudFormationCustomResourceEvent) -> Dict:
    """
    Handle Update event for the custom resource.

    Args:
        event: CloudFormation custom resource event

    Returns:
        Dict containing physical ID and resource data
    """
    logger.info("Handling Update request")
    response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
    attr = response["UserPool"]
    lambda_config = attr.get("LambdaConfig", {})

    old_triggers = event.old_resource_properties["Triggers"]
    new_triggers = event.resource_properties["Triggers"]

    updated_lambda_config = {
        **{k: v for k, v in lambda_config.items() if k not in old_triggers.keys()},
        **new_triggers,
    }

    update_user_pool_lambda_config(
        USER_POOL_ID,
        attr,
        lambda_config=updated_lambda_config,
    )

    return {
        "PhysicalResourceId": event.physical_resource_id,
        "Data": event.resource_properties,
    }


@tracer.capture_method
def on_delete(event: CloudFormationCustomResourceEvent) -> Dict:
    """
    Handle Delete event for the custom resource.

    Args:
        event: CloudFormation custom resource event

    Returns:
        Dict containing physical ID and resource data
    """
    logger.info("Handling Delete request")
    response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
    attr = response["UserPool"]
    lambda_config = attr.get("LambdaConfig", {})
    triggers = event.resource_properties["Triggers"]

    updated_lambda_config = {
        k: v for k, v in lambda_config.items() if k not in triggers.keys()
    }

    update_user_pool_lambda_config(
        USER_POOL_ID,
        attr,
        lambda_config=updated_lambda_config,
    )

    return {
        "PhysicalResourceId": event.physical_resource_id,
        "Data": event.resource_properties,
    }


@event_source(data_class=CloudFormationCustomResourceEvent)
@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
def handler(event: CloudFormationCustomResourceEvent, context: LambdaContext) -> Dict:
    """
    Lambda function to manage Cognito user pool triggers as a custom resource.

    Args:
        event: The CloudFormation custom resource event
        context: The Lambda context object

    Returns:
        Dict containing the CloudFormation custom resource response

    Raises:
        ClientError: If there is an error with the AWS API calls
    """
    try:
        if event.request_type == "Create":
            return on_create(event)
        elif event.request_type == "Update":
            return on_update(event)
        elif event.request_type == "Delete":
            return on_delete(event)
        else:
            raise ValueError(f"Invalid request type: {event.request_type}")

    except ClientError as err:
        logger.error(
            "AWS API error occurred",
            extra={
                "error_code": err.response["Error"]["Code"],
                "error_message": err.response["Error"]["Message"],
                "request_id": err.response.get("ResponseMetadata", {}).get("RequestId"),
                "http_status_code": err.response.get("ResponseMetadata", {}).get(
                    "HTTPStatusCode"
                ),
            },
        )
        raise

    except Exception as err:
        logger.exception(
            "Unexpected error occurred",
            extra={
                "error_type": type(err).__name__,
                "error_message": str(err),
            },
        )
        raise
