"""
Lambda handler for Cognito Trigger custom resource.

This module implements the Lambda function that handles the creation, update,
and deletion of Cognito User Pool triggers through CloudFormation custom resources.
"""

import json
import os
import signal
from typing import Any, Dict

import boto3
import urllib3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

USER_POOL_ID = os.environ["USER_POOL_ID"]

logger = Logger()
tracer = Tracer()
cognito = boto3.client("cognito-idp")
http = urllib3.PoolManager()


def send_cfn_response(
    event: Dict[str, Any],
    context: LambdaContext,
    status: str,
    data: Dict[str, Any],
    physical_resource_id: str | None = None,
) -> None:
    """
    Send a response to CloudFormation about the result of the custom resource.

    Args:
        event: The Lambda event containing CloudFormation custom resource request
        context: The Lambda context
        status: SUCCESS or FAILED
        data: Response data to send back
        physical_resource_id: Optional resource ID (defaults to Lambda function ARN)
    """
    response_url = event["ResponseURL"]

    if not physical_resource_id:
        physical_resource_id = context.invoked_function_arn

    logger.info(
        f"Sending response to {response_url}",
        extra={
            "status": status,
            "data": data,
            "physical_resource_id": physical_resource_id,
        },
    )

    response_body = {
        "Status": status,
        "Reason": f"See CloudWatch Log Stream: {context.log_stream_name}",
        "PhysicalResourceId": physical_resource_id,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "NoEcho": False,
        "Data": data,
    }

    encoded_response = json.dumps(response_body).encode("utf-8")

    headers = {"content-type": "", "content-length": str(len(encoded_response))}

    try:
        response = http.request(
            "PUT",
            response_url,
            body=encoded_response,
            headers=headers,
            retries=urllib3.Retry(3),
        )
        logger.info(
            "CloudFormation response sent successfully",
            extra={
                "status_code": response.status,
                "response": response.data.decode("utf-8"),
            },
        )
    except Exception as e:
        logger.exception(
            "Failed to send CloudFormation response", extra={"error": str(e)}
        )
        raise


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


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Handle CloudFormation custom resource requests for Cognito trigger management.

    Args:
        event: Lambda event containing CloudFormation custom resource request
        context: Lambda context

    Returns:
        CloudFormation custom resource response
    """
    try:
        request_type = event["RequestType"]
        physical_id = event.get("PhysicalResourceId", f"{USER_POOL_ID}-triggers")
        resource_properties = event["ResourceProperties"]
        triggers = resource_properties["Triggers"]

        logger.info(
            "Processing request",
            extra={
                "request_type": request_type,
                "physical_id": physical_id,
                "triggers": triggers,
            },
        )

        if request_type == "Create" or request_type == "Update":
            response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
            attr = response["UserPool"]
            lambda_config = attr.get("LambdaConfig", {})

            if request_type == "Create":
                lambda_config = {**lambda_config, **triggers}
            else:
                old_triggers = event.get("OldResourceProperties", {}).get(
                    "Triggers", {}
                )
                lambda_config = {
                    **{
                        k: v
                        for k, v in lambda_config.items()
                        if k not in old_triggers.keys()
                    },
                    **triggers,
                }

            update_user_pool_lambda_config(USER_POOL_ID, attr, lambda_config)

        elif request_type == "Delete":
            response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
            attr = response["UserPool"]
            lambda_config = attr.get("LambdaConfig", {})

            lambda_config = {
                k: v for k, v in lambda_config.items() if k not in triggers.keys()
            }

            update_user_pool_lambda_config(USER_POOL_ID, attr, lambda_config)

        send_cfn_response(
            event,
            context,
            "SUCCESS",
            {"Message": f"Operation {request_type} completed successfully"},
            physical_id,
        )

        return {
            "PhysicalResourceId": physical_id,
            "Data": resource_properties,
        }

    except Exception as e:
        logger.exception("Failed to process request")
        send_cfn_response(
            event,
            context,
            "FAILED",
            {
                "Error": str(e),
                "Message": f"Failed to process {event.get('RequestType')} request",
            },
            physical_id if "physical_id" in locals() else None,
        )
        raise


def timeout_handler(_signal: int, _frame: Any) -> None:
    """
    Handle Lambda timeout signals gracefully by logging and raising exception.

    This function catches SIGALRM signals sent when Lambda is about to timeout,
    allowing us to log the timeout and raise a proper exception rather than
    having the function silently killed.

    Args:
        _signal: Signal number (unused but required by signal.signal)
        _frame: Current stack frame (unused but required by signal.signal)

    Raises:
        Exception: Always raises with "Lambda timeout" message

    Note:
        Uses _signal and _frame parameter names to indicate they are unused
        but required by the signal handling interface.
    """
    logger.error("Lambda timeout occurred")
    raise Exception("Lambda timeout")


signal.signal(signal.SIGALRM, timeout_handler)
