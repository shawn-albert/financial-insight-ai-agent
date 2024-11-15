#!/usr/bin/env python3
"""
Financial Insight Agent CDK Application.

This module serves as the entry point for deploying the Financial Insight Agent
infrastructure using AWS CDK. It orchestrates the deployment of various stacks
including authentication, API, database, and frontend components.
"""

import os
from typing import Any

import aws_cdk as cdk
from aws_cdk import App
from lib.stacks.agent_stack import FinancialInsightAgentStack
from lib.stacks.regional_resources_stack import RegionalResourcesStack
from lib.stacks.waf_stack import WafStack


def get_context_value(app: App, key: str) -> Any:
    """
    Retrieve a context value from the CDK app configuration.

    Args:
        app: The CDK application instance
        key: The context key to retrieve

    Returns:
        The context value

    Raises:
        ValueError: If the context value is not found
    """
    value = app.node.try_get_context(key)
    if value is None:
        raise ValueError(f"Context value '{key}' not found")
    return value


def main() -> None:
    """
    Main entry point for the CDK application deployment.

    This function orchestrates the creation and deployment of all required stacks
    for the Financial Insight Agent, including:
    - WAF configuration for security
    - Regional resources for Bedrock integration
    - Main application stack with all core functionality
    """
    app = cdk.App()

    bedrock_region: str = get_context_value(app, "bedrock_region")
    deployment_region: str = os.getenv("CDK_DEFAULT_REGION", "")
    account_id: str = os.getenv("CDK_DEFAULT_ACCOUNT", "")

    allowed_ipv4_ranges: list[str] = (
        app.node.try_get_context("allowed_ipv4_address_ranges") or []
    )
    allowed_ipv6_ranges: list[str] = (
        app.node.try_get_context("allowed_ipv6_address_ranges") or []
    )
    allowed_signup_domains: list[str] = (
        app.node.try_get_context("allowed_signup_email_domains") or []
    )
    identity_providers: list[dict] = (
        app.node.try_get_context("identity_providers") or []
    )
    user_pool_domain: str = app.node.try_get_context("user_pool_domain_prefix")
    auto_join_groups: list[str] = (
        app.node.try_get_context("auto_join_user_groups") or []
    )

    enable_mistral: bool = bool(app.node.try_get_context("enable_mistral"))
    self_signup_enabled: bool = bool(app.node.try_get_context("self_signup_enabled"))
    use_standby_replicas: bool = bool(app.node.try_get_context("enable_rag_replicas"))
    enable_cross_region: bool = bool(
        app.node.try_get_context("enable_bedrock_cross_region_inference")
    )

    waf = WafStack(
        app,
        "FinancialInsightWafStack",
        env=cdk.Environment(region="us-east-1", account=account_id),
        allowed_ipv4_ranges=allowed_ipv4_ranges,
        allowed_ipv6_ranges=allowed_ipv6_ranges,
    )

    regional_resources = RegionalResourcesStack(
        app,
        "FinancialInsightRegionalStack",
        env=cdk.Environment(region=bedrock_region, account=account_id),
        cross_region_references=True,
    )

    agent = FinancialInsightAgentStack(
        app,
        "FinancialInsightAgentStack",
        env=cdk.Environment(region=deployment_region, account=account_id),
        cross_region_references=True,
        bedrock_region=bedrock_region,
        web_acl_id=waf.web_acl_arn.value,
        enable_ipv6=waf.ipv6_enabled,
        identity_providers=identity_providers,
        user_pool_domain_prefix=user_pool_domain,
        allowed_signup_email_domains=allowed_signup_domains,
        auto_join_user_groups=auto_join_groups,
        enable_mistral=enable_mistral,
        self_signup_enabled=self_signup_enabled,
        document_bucket=regional_resources.document_bucket,
        use_standby_replicas=use_standby_replicas,
        enable_bedrock_cross_region_inference=enable_cross_region,
    )

    agent.add_dependency(waf)
    agent.add_dependency(regional_resources)

    app.synth()


if __name__ == "__main__":
    main()
