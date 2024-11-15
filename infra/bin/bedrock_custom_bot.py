"""
Main entry point for the Financial Insight Agent CDK application.

This module initializes and configures the main application stacks including:
- WAF for frontend protection
- Regional resources for Bedrock integration
- Main agent functionality
"""

#!/usr/bin/env python3

import os
import sys
from pathlib import Path
from typing import List

import aws_cdk as cdk

project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

from lib.utils.identity_provider import IdentityProviderConfig
from stacks.agent_stack import FinancialInsightAgentStack
from stacks.regional_resources_stack import RegionalResourcesStack
from stacks.waf_stack import WafStack

app = cdk.App()

BEDROCK_REGION = app.node.try_get_context("bedrock_region")

ALLOWED_IPV4_RANGES: List[str] = app.node.try_get_context("allowed_ipv4_address_ranges")
ALLOWED_IPV6_RANGES: List[str] = app.node.try_get_context("allowed_ipv6_address_ranges")

ALLOWED_SIGNUP_DOMAINS: List[str] = app.node.try_get_context(
    "allowed_signup_email_domains"
)
IDENTITY_PROVIDERS: List[IdentityProviderConfig] = app.node.try_get_context(
    "identity_providers"
)
USER_POOL_DOMAIN_PREFIX: str = app.node.try_get_context("user_pool_domain_prefix")
AUTO_JOIN_GROUPS: List[str] = app.node.try_get_context("auto_join_user_groups")

ENABLE_MISTRAL: bool = bool(app.node.try_get_context("enable_mistral"))
SELF_SIGNUP_ENABLED: bool = bool(app.node.try_get_context("self_signup_enabled"))
USE_STANDBY_REPLICAS: bool = bool(app.node.try_get_context("enable_rag_replicas"))
ENABLE_BEDROCK_CROSS_REGION: bool = bool(
    app.node.try_get_context("enable_bedrock_cross_region_inference")
)

waf = WafStack(
    app,
    "FrontendWafStack",
    env=cdk.Environment(
        region="us-east-1",
    ),
    allowed_ipv4_ranges=ALLOWED_IPV4_RANGES,
    allowed_ipv6_ranges=ALLOWED_IPV6_RANGES,
)

bedrock_resources = RegionalResourcesStack(
    app,
    "BedrockRegionResourcesStack",
    env=cdk.Environment(
        region=BEDROCK_REGION,
    ),
    cross_region_references=True,
)

agent = FinancialInsightAgentStack(
    app,
    "FinancialInsightAgentStack",
    env=cdk.Environment(
        region=os.getenv("CDK_DEFAULT_REGION"),
    ),
    cross_region_references=True,
    bedrock_region=BEDROCK_REGION,
    web_acl_id=waf.web_acl_arn.value,
    enable_ipv6=waf.ipv6_enabled,
    identity_providers=IDENTITY_PROVIDERS,
    user_pool_domain_prefix=USER_POOL_DOMAIN_PREFIX,
    allowed_signup_email_domains=ALLOWED_SIGNUP_DOMAINS,
    auto_join_user_groups=AUTO_JOIN_GROUPS,
    enable_mistral=ENABLE_MISTRAL,
    self_signup_enabled=SELF_SIGNUP_ENABLED,
    document_bucket=bedrock_resources.document_bucket,
    use_standby_replicas=USE_STANDBY_REPLICAS,
    enable_bedrock_cross_region_inference=ENABLE_BEDROCK_CROSS_REGION,
)

agent.add_dependency(waf)
agent.add_dependency(bedrock_resources)

app.synth()
