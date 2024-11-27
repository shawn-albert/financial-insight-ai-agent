"""
Web ACL Configuration Module for Published APIs.

This module implements AWS WAF Web ACL infrastructure for published APIs, providing IP-based
access control through IPv4 and IPv6 rule sets. It supports regional scope and configurable
IP range allowlists with CloudWatch metrics integration.

The module handles:
- IPv4 and IPv6 IP set creation
- WAF rule configuration
- Default block actions
- CloudWatch metrics configuration
- ARN management and output
"""

import logging
from dataclasses import dataclass
from typing import List

from aws_cdk import CfnOutput
from aws_cdk import aws_wafv2 as wafv2
from constructs import Construct

logger = logging.getLogger(__name__)


@dataclass
class WebAclForPublishedApiProps:
    """
    Properties for Web ACL configuration.

    Attributes:
        allowed_ipv4_address_ranges: List of IPv4 CIDR ranges to allow
        allowed_ipv6_address_ranges: List of IPv6 CIDR ranges to allow
    """

    allowed_ipv4_address_ranges: List[str]
    allowed_ipv6_address_ranges: List[str]


class WebAclForPublishedApi(Construct):
    """
    Web ACL infrastructure for published API protection.

    This construct creates a Web ACL with IP-based access control rules.
    It supports both IPv4 and IPv6 address ranges and implements a default
    block action for unmatched requests.

    Attributes:
        web_acl_arn: ARN of the created Web ACL
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: WebAclForPublishedApiProps,
    ) -> None:
        """
        Initialize WebAclForPublishedApi construct.

        Args:
            scope: CDK construct scope
            construct_id: Unique identifier for this construct
            props: Configuration properties for the Web ACL

        Raises:
            ValueError: If no IP ranges are specified in either IPv4 or IPv6
        """
        super().__init__(scope, construct_id)

        rules = self._create_ip_rules(props)

        if not rules:
            raise ValueError(
                "One or more allowed IP ranges for the published API must be specified in IPv4 or IPv6."
            )

        web_acl = wafv2.CfnWebACL(
            self,
            "WebAcl",
            default_action={"block": {}},
            name=f"ApiWebAcl-{construct_id}",
            scope="REGIONAL",
            visibility_config={
                "cloudWatchMetricsEnabled": True,
                "metricName": "WebAcl",
                "sampledRequestsEnabled": True,
            },
            rules=rules,
        )

        CfnOutput(
            self,
            "WebAclArn",
            value=web_acl.attr_arn,
        )

        self.web_acl_arn = web_acl.attr_arn

    def _create_ip_rules(
        self,
        props: WebAclForPublishedApiProps,
    ) -> List[wafv2.CfnWebACL.RuleProperty]:
        """
        Create IP-based WAF rules for both IPv4 and IPv6 ranges.

        Args:
            props: Web ACL configuration properties

        Returns:
            List of WAF rule properties for the Web ACL
        """
        rules = []

        if props.allowed_ipv4_address_ranges:
            ipv4_set = wafv2.CfnIPSet(
                self,
                "IpV4Set",
                ip_address_version="IPV4",
                scope="REGIONAL",
                addresses=props.allowed_ipv4_address_ranges,
            )
            rules.append(
                self._create_rule_property(
                    priority=0,
                    name="WebAclIpV4RuleSet",
                    ip_set_arn=ipv4_set.attr_arn,
                )
            )

        if props.allowed_ipv6_address_ranges:
            ipv6_set = wafv2.CfnIPSet(
                self,
                "IpV6Set",
                ip_address_version="IPV6",
                scope="REGIONAL",
                addresses=props.allowed_ipv6_address_ranges,
            )
            rules.append(
                self._create_rule_property(
                    priority=1,
                    name="WebAclIpV6RuleSet",
                    ip_set_arn=ipv6_set.attr_arn,
                )
            )

        return rules

    def _create_rule_property(
        self,
        priority: int,
        name: str,
        ip_set_arn: str,
    ) -> wafv2.CfnWebACL.RuleProperty:
        """
        Create a WAF rule property for an IP set.

        Args:
            priority: Rule priority number
            name: Name for the rule
            ip_set_arn: ARN of the IP set to reference

        Returns:
            Configured WAF rule property
        """
        return wafv2.CfnWebACL.RuleProperty(
            priority=priority,
            name=name,
            action={"allow": {}},
            visibility_config={
                "cloudWatchMetricsEnabled": True,
                "metricName": "PublishedApiWebAcl",
                "sampledRequestsEnabled": True,
            },
            statement={
                "ipSetReferenceStatement": {"arn": ip_set_arn},
            },
        )
