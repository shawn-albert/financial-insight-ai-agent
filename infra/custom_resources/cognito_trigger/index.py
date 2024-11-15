"""
Lambda handler for Cognito Trigger custom resource.

This module implements the Lambda function that handles the creation, update,
and deletion of Cognito User Pool triggers through CloudFormation custom resources.
"""

import os
from typing import Any, Dict

import boto3
import cfnresponse
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

tracer = Tracer()
logger = Logger()
cognito = boto3.client("cognito-idp")
USER_POOL_ID = os.environ["USER_POOL_ID"]


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def handler(event: Dict[str, Any], context: LambdaContext) -> None:
    """
    Handle custom resource lifecycle events for Cognito triggers.

    Args:
        event: CloudFormation custom resource event
        context: Lambda execution context
    """
    request_type = event["RequestType"]
    physical_resource_id = event.get("PhysicalResourceId") or f"{USER_POOL_ID}-triggers"

    resource_properties = event["ResourceProperties"]
    triggers = resource_properties["Triggers"]

    try:
        if request_type == "Create":
            _handle_create(triggers)
        elif request_type == "Update":
            old_triggers = event["OldResourceProperties"]["Triggers"]
            _handle_update(triggers, old_triggers)
        elif request_type == "Delete":
            _handle_delete(triggers)

        cfnresponse.send(
            event,
            context,
            cfnresponse.SUCCESS,
            resource_properties,
            physical_resource_id,
        )

    except Exception:
        logger.exception("Error handling custom resource request")
        cfnresponse.send(
            event,
            context,
            cfnresponse.FAILED,
            None,
            physical_resource_id,
        )


@tracer.capture_method
def _handle_create(triggers: Dict[str, str]) -> None:
    """
    Handle creation of Cognito triggers.

    Args:
        triggers: Dictionary mapping trigger types to Lambda ARNs
    """
    response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
    attr = response["UserPool"]
    lambda_config = attr.get("LambdaConfig", {})

    _update_user_pool_config(attr, {**lambda_config, **triggers})


@tracer.capture_method
def _handle_update(triggers: Dict[str, str], old_triggers: Dict[str, str]) -> None:
    """
    Handle updates to existing Cognito triggers.

    Args:
        triggers: New trigger configuration
        old_triggers: Previous trigger configuration
    """
    response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
    attr = response["UserPool"]
    lambda_config = attr.get("LambdaConfig", {})

    filtered_config = {
        k: v for k, v in lambda_config.items() if k not in old_triggers.keys()
    }

    _update_user_pool_config(attr, {**filtered_config, **triggers})


@tracer.capture_method
def _handle_delete(triggers: Dict[str, str]) -> None:
    """
    Handle deletion of Cognito triggers.

    Args:
        triggers: Triggers to remove
    """
    response = cognito.describe_user_pool(UserPoolId=USER_POOL_ID)
    attr = response["UserPool"]
    lambda_config = attr.get("LambdaConfig", {})

    filtered_config = {
        k: v for k, v in lambda_config.items() if k not in triggers.keys()
    }

    _update_user_pool_config(attr, filtered_config)


@tracer.capture_method
def _update_user_pool_config(
    attr: Dict[str, Any], lambda_config: Dict[str, str]
) -> None:
    """
    Update Cognito User Pool configuration.

    Args:
        attr: User pool attributes
        lambda_config: Lambda trigger configuration
    """
    update_params = {
        k: v
        for k, v in attr.items()
        if k
        in [
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
    }

    if "TemporaryPasswordValidityDays" in attr.get("Policies", {}).get(
        "PasswordPolicy", {}
    ):
        update_params.get("AdminCreateUserConfig", {}).pop(
            "UnusedAccountValidityDays", None
        )

    cognito.update_user_pool(
        UserPoolId=USER_POOL_ID,
        **update_params,
        LambdaConfig=lambda_config,
    )
