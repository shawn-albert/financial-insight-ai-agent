"""Lambda function for managing Cognito User Pool triggers via CloudFormation custom resources.

This module implements a Lambda handler that manages the lifecycle of Cognito User Pool
triggers through CloudFormation custom resources. It supports creating, updating, and
deleting trigger configurations while maintaining other user pool settings.
"""

import json
import os
import signal
from typing import Any, Dict, Optional

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
    physical_resource_id: Optional[str] = None,
) -> None:
    """Send response to CloudFormation regarding the success or failure of the custom resource operation.

    Args:
        event: Lambda event containing the CloudFormation request details
        context: Lambda runtime context
        status: Status of the operation (SUCCESS/FAILED)
        data: Data to be sent back to CloudFormation
        physical_resource_id: Unique identifier for the custom resource

    Raises:
        Exception: If sending the response to CloudFormation fails
    """
    response_url = event["ResponseURL"]
    physical_resource_id = physical_resource_id or context.invoked_function_arn

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

    response = http.request(
        "PUT",
        response_url,
        body=encoded_response,
        headers=headers,
        retries=urllib3.Retry(3),
    )

    logger.info(f"CloudFormation response status code: {response.status}")


def update_user_pool_lambda_config(
    user_pool_id: str,
    user_pool_attributes: Dict[str, Any],
    lambda_config: Dict[str, str],
) -> None:
    """Update the Lambda trigger configuration for a Cognito User Pool.

    Args:
        user_pool_id: Identifier of the Cognito User Pool
        user_pool_attributes: Current attributes of the User Pool
        lambda_config: New Lambda trigger configuration to apply

    Raises:
        ClientError: If the User Pool update fails
    """
    if "TemporaryPasswordValidityDays" in user_pool_attributes.get("Policies", {}).get(
        "PasswordPolicy", {}
    ):
        admin_config = user_pool_attributes.get("AdminCreateUserConfig", {})
        admin_config.pop("UnusedAccountValidityDays", None)

    valid_attributes = [
        "Policies",
        "DeletionProtection",
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

    update_params = {
        k: v for k, v in user_pool_attributes.items() if k in valid_attributes
    }

    cognito.update_user_pool(
        UserPoolId=user_pool_id,
        **update_params,
        LambdaConfig=lambda_config,
    )


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """Handle CloudFormation custom resource requests for Cognito User Pool trigger management.

    Args:
        event: CloudFormation custom resource event
        context: Lambda runtime context

    Returns:
        Dict containing the physical resource ID and resource properties

    Raises:
        Exception: If the requested operation fails
    """
    request_type = event["RequestType"]
    physical_id = event.get("PhysicalResourceId", f"{USER_POOL_ID}-triggers")
    resource_properties = event["ResourceProperties"]
    triggers = resource_properties["Triggers"]

    try:
        response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
        user_pool_attributes = response["UserPool"]
        lambda_config = user_pool_attributes.get("LambdaConfig", {})

        if request_type == "Create":
            new_lambda_config = {**lambda_config, **triggers}
        elif request_type == "Update":
            old_triggers = event["OldResourceProperties"]["Triggers"]
            new_lambda_config = {
                **{
                    k: v
                    for k, v in lambda_config.items()
                    if k not in old_triggers.keys()
                },
                **triggers,
            }
        else:
            new_lambda_config = {
                k: v for k, v in lambda_config.items() if k not in triggers.keys()
            }

        update_user_pool_lambda_config(
            USER_POOL_ID, user_pool_attributes, new_lambda_config
        )

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


def timeout_handler(signal_number: int, frame: Any) -> None:
    """Handle Lambda timeouts gracefully by raising a custom exception.

    Args:
        signal_number: Signal number received
        frame: Current stack frame

    Raises:
        Exception: Always raises with "Lambda timeout" message
    """
    raise Exception("Lambda timeout")


signal.signal(signal.SIGALRM, timeout_handler)
