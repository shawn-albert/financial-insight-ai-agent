"""
Entry point for Financial Insight Agent CDK Application.

This module controls the deployment of CDK stacks including:
- Frontend and access security via WAF
- Regional Bedrock resources and dependencies
- Core authentication and API infrastructure
"""

#!/usr/bin/env python3

import os
import sys
from pathlib import Path

import aws_cdk as cdk

project_root = str(Path(__file__).parent)
sys.path.insert(0, project_root)

from stacks.agent_stack import FinancialInsightAgentStack
from stacks.regional_resources_stack import RegionalResourcesStack
from stacks.waf_stack import WafStack

app = cdk.App()

BEDROCK_REGION = app.node.try_get_context("bedrockRegion")
ALLOWED_IPV4_RANGES = app.node.try_get_context("allowedIpV4AddressRanges") or []
ALLOWED_IPV6_RANGES = app.node.try_get_context("allowedIpV6AddressRanges") or []
ALLOWED_SIGNUP_DOMAINS = app.node.try_get_context("allowedSignUpEmailDomains") or []
IDENTITY_PROVIDERS = app.node.try_get_context("identityProviders") or []
USER_POOL_DOMAIN_PREFIX = app.node.try_get_context("userPoolDomainPrefix")
AUTO_JOIN_GROUPS = app.node.try_get_context("autoJoinUserGroups") or []

ENABLE_MISTRAL = bool(app.node.try_get_context("enableMistral"))
SELF_SIGNUP_ENABLED = bool(app.node.try_get_context("selfSignUpEnabled"))
USE_STANDBY_REPLICAS = bool(app.node.try_get_context("enableRagReplicas"))
ENABLE_BEDROCK_CROSS_REGION = bool(
    app.node.try_get_context("enableBedrockCrossRegionInference")
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
