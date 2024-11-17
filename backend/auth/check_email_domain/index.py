"""
Lambda handler for validating email domains during Cognito pre-signup.

This module implements email domain validation against an allowed list
of domains configured through environment variables.
"""

import json
import os
from typing import Any, Dict, List, Optional

from aws_lambda_powertools import Logger, Metrics, Tracer
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR: Optional[str] = os.environ.get(
    "ALLOWED_SIGN_UP_EMAIL_DOMAINS"
)
ALLOWED_SIGN_UP_EMAIL_DOMAINS: List[str] = (
    json.loads(ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR)
    if ALLOWED_SIGN_UP_EMAIL_DOMAINS_STR
    else []
)

logger = Logger()
tracer = Tracer()
metrics = Metrics()


@tracer.capture_method
def check_email_domain(email: str) -> bool:
    """
    Validate if the email domain is allowed.

    Args:
        email: Email address to validate

    Returns:
        bool: True if domain is allowed, False otherwise
    """
    if not ALLOWED_SIGN_UP_EMAIL_DOMAINS:
        logger.warning("No allowed email domains configured")
        return False

    if email.count("@") != 1:
        logger.warning("Invalid email format", extra={"email": email})
        return False

    domain = email.split("@")[1]
    is_allowed = domain in ALLOWED_SIGN_UP_EMAIL_DOMAINS

    logger.info(
        "Email domain validation result",
        extra={
            "domain": domain,
            "is_allowed": is_allowed,
            "allowed_domains": ALLOWED_SIGN_UP_EMAIL_DOMAINS,
        },
    )

    metrics.add_metric(
        name="EmailDomainValidation",
        unit=MetricUnit.Count,
        value=1,
        domain=domain,
        result="allowed" if is_allowed else "blocked",
    )

    return is_allowed


@tracer.capture_lambda_handler
@logger.inject_lambda_context(log_event=True)
@metrics.log_metrics
def handler(event: Dict[str, Any], context: LambdaContext) -> Dict[str, Any]:
    """
    Handle Cognito pre-signup email domain validation.

    Args:
        event: Cognito pre-signup trigger event
        context: Lambda execution context

    Returns:
        Dict containing the original event data

    Raises:
        ValueError: If email is missing or improperly formatted
        Exception: If domain validation fails
    """
    try:
        user_attributes = event["request"]["userAttributes"]
        email = user_attributes.get("email")

        if not email:
            logger.error("Email missing from user attributes")
            raise ValueError("Email attribute is required")

        logger.info(
            "Validating email domain",
            extra={
                "email_domain": email.split("@")[1],
            },
        )

        if check_email_domain(email):
            metrics.add_metric(
                name="PreSignupTrigger",
                unit=MetricUnit.Count,
                value=1,
                result="success",
            )
            return event

        metrics.add_metric(
            name="PreSignupTrigger",
            unit=MetricUnit.Count,
            value=1,
            result="blocked",
        )
        raise ValueError("Email domain not allowed")

    except Exception as e:
        logger.exception(
            "Pre-signup validation failed",
            extra={
                "error_type": type(e).__name__,
                "error_message": str(e),
            },
        )
        raise
