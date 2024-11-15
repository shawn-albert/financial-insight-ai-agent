"""
WAF (Web Application Firewall) Construct Implementation for Financial Insight Agent.

This module implements AWS WAF configuration for protecting the application from
unauthorized access and potential attacks. It creates IP-based rules for both IPv4
and IPv6 traffic and configures them in a Web ACL for CloudFront distributions.
"""

from dataclasses import dataclass
from typing import List

from aws_cdk import CfnOutput, Stack, StackProps
from aws_cdk import aws_wafv2 as wafv2

from constructs import Construct


@dataclass
class WafStackProps(StackProps):
    """
    Properties for WAF stack configuration.

    Attributes:
        allowed_ipv4_ranges: List of allowed IPv4 CIDR ranges
        allowed_ipv6_ranges: List of allowed IPv6 CIDR ranges
    """

    allowed_ipv4_ranges: List[str]
    allowed_ipv6_ranges: List[str]


class WafStack(Stack):
    """
    WAF stack for protecting the Financial Insight Agent application.

    This stack creates and manages WAF resources including:
    - IP Sets for both IPv4 and IPv6
    - Web ACL with IP-based rules
    - CloudWatch metrics configuration

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
    ) -> None:
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

        self.web_acl_arn = CfnOutput(
            self,
            "WebAclId",
            value=web_acl.attr_arn,
            description="ARN of the WAF Web ACL",
        )
