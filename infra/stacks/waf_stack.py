"""
WAF Stack Implementation for Financial Insight Agent.

This module implements the AWS WAF configuration for protecting the application's
frontend resources. It creates IP-based rules for both IPv4 and IPv6 addresses
and configures them in a Web ACL that can be attached to CloudFront distributions.
"""

from typing import List

from aws_cdk import CfnOutput, Stack, StackProps
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct


class WafStackProps(StackProps):
    """
    Configuration properties for the WAF stack.

    Attributes:
        allowed_ipv4_ranges: List of allowed IPv4 CIDR ranges
        allowed_ipv6_ranges: List of allowed IPv6 CIDR ranges
    """

    def __init__(
        self, allowed_ipv4_ranges: List[str], allowed_ipv6_ranges: List[str], **kwargs
    ):
        """
        Initialize WAF stack properties.

        Args:
            allowed_ipv4_ranges: List of allowed IPv4 CIDR ranges
            allowed_ipv6_ranges: List of allowed IPv6 CIDR ranges
            **kwargs: Additional stack properties
        """
        super().__init__(**kwargs)
        self.allowed_ipv4_ranges = allowed_ipv4_ranges
        self.allowed_ipv6_ranges = allowed_ipv6_ranges


class WafStack(Stack):
    """
    AWS WAF stack implementation for the Financial Insight Agent.

    This stack creates a Web ACL with IP-based rules for both IPv4 and IPv6
    traffic. It's designed to be attached to CloudFront distributions to provide
    IP-based access control.

    Attributes:
        web_acl_arn: ARN of the created Web ACL
        ipv6_enabled: Boolean indicating if IPv6 rules are configured
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        allowed_ipv4_ranges: List[str],
        allowed_ipv6_ranges: List[str],
        **kwargs,
    ):
        """
        Initialize the WAF stack.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for the stack
            allowed_ipv4_ranges: List of allowed IPv4 CIDR ranges
            allowed_ipv6_ranges: List of allowed IPv6 CIDR ranges
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        rules: List[wafv2.CfnWebACL.RuleProperty] = []
        self.ipv6_enabled = False

        if allowed_ipv4_ranges:
            ipv4_set = wafv2.CfnIPSet(
                self,
                "FrontendIpV4Set",
                ip_address_version="IPV4",
                scope="CLOUDFRONT",
                addresses=allowed_ipv4_ranges,
            )

            rules.append(
                wafv2.CfnWebACL.RuleProperty(
                    priority=0,
                    name="FrontendWebAclIpV4RuleSet",
                    action=wafv2.CfnWebACL.RuleActionProperty(allow={}),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="FrontendWebAcl",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        ip_set_reference_statement={"arn": ipv4_set.attr_arn}
                    ),
                )
            )

        if allowed_ipv6_ranges:
            ipv6_set = wafv2.CfnIPSet(
                self,
                "FrontendIpV6Set",
                ip_address_version="IPV6",
                scope="CLOUDFRONT",
                addresses=allowed_ipv6_ranges,
            )

            rules.append(
                wafv2.CfnWebACL.RuleProperty(
                    priority=1,
                    name="FrontendWebAclIpV6RuleSet",
                    action=wafv2.CfnWebACL.RuleActionProperty(allow={}),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="FrontendWebAcl",
                        sampled_requests_enabled=True,
                    ),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        ip_set_reference_statement={"arn": ipv6_set.attr_arn}
                    ),
                )
            )
            self.ipv6_enabled = True

        if not rules:
            raise ValueError(
                "One or more allowed IP ranges must be specified in IPv4 or IPv6."
            )

        web_acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(block={}),
            name="FrontendWebAcl",
            scope="CLOUDFRONT",
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="FrontendWebAcl",
                sampled_requests_enabled=True,
            ),
            rules=rules,
        )

        self.web_acl_arn = CfnOutput(self, "WebAclId", value=web_acl.attr_arn)
