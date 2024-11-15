"""
Authentication Construct Implementation for Financial Insight Agent.

This module implements authentication and authorization using Amazon Cognito,
supporting multiple identity providers, user groups, and custom triggers
for user management.
"""

from dataclasses import dataclass
from typing import List

from aws_cdk import CustomResource, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from cdk_aws_lambda_powertools_layer import LambdaPowertoolsLayer

from constructs import Construct


@dataclass
class AuthProps:
    """
    Properties for Authentication construct configuration.

    Attributes:
        origin: Frontend application origin URL
        user_pool_domain_prefix: Prefix for Cognito domain
        identity_providers: List of identity provider configurations
        allowed_signup_email_domains: List of allowed email domains
        auto_join_user_groups: Groups users automatically join
        self_signup_enabled: Whether self-signup is enabled
    """

    origin: str
    user_pool_domain_prefix: str
    identity_providers: List[dict]
    allowed_signup_email_domains: List[str]
    auto_join_user_groups: List[str]
    self_signup_enabled: bool


class Auth(Construct):
    """
    Authentication infrastructure for the Financial Insight Agent.

    This construct creates and manages Cognito user pools, clients, and identity
    providers. It supports email domain restrictions, automatic group assignment,
    and multiple authentication providers.

    Attributes:
        user_pool: Cognito user pool for authentication
        client: Cognito user pool client
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: AuthProps,
    ) -> None:
        """
        Initialize the Authentication construct.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for this construct
            props: Configuration properties for authentication
        """
        super().__init__(scope, construct_id)

        powertools_layer = LambdaPowertoolsLayer(
            self,
            "PowertoolsLayer",
            version="3.3.0",
            include_extras=True,
        )

        common_lambda_environment = {
            "POWERTOOLS_SERVICE_NAME": "financial-insight-auth",
            "POWERTOOLS_METRICS_NAMESPACE": "FinancialInsightAgent",
            "LOG_LEVEL": "INFO",
        }

        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            password_policy=cognito.PasswordPolicy(
                require_uppercase=True,
                require_symbols=True,
                require_digits=True,
                min_length=8,
            ),
            self_sign_up_enabled=props.self_signup_enabled,
            sign_in_aliases=cognito.SignInAliases(
                username=False,
                email=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        client_props = self._configure_client_props(props)
        self.client = self.user_pool.add_client("Client", **client_props)

        if props.identity_providers:
            self._configure_identity_providers(props)
            self.user_pool.add_domain(
                "Domain",
                cognito_domain=cognito.CognitoDomainOptions(
                    domain_prefix=props.user_pool_domain_prefix,
                ),
            )

        self._create_user_groups()

        if props.auto_join_user_groups:
            self._configure_auto_join_groups(
                props.auto_join_user_groups,
                powertools_layer,
                common_lambda_environment,
            )

        if props.allowed_signup_email_domains:
            self._configure_email_domain_check(
                props.allowed_signup_email_domains,
                powertools_layer,
                common_lambda_environment,
            )

        self._create_outputs()

    def _configure_auto_join_groups(
        self,
        groups: List[str],
        powertools_layer: lambda_.ILayerVersion,
        lambda_env: dict,
    ) -> None:
        """
        Configure automatic group assignment for new users.

        Args:
            groups: List of groups to automatically join
            powertools_layer: AWS Lambda Powertools layer
            lambda_env: Common Lambda environment variables
        """
        add_to_groups_function = lambda_.Function(
            self,
            "AddUserToGroups",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="add_user_to_groups.handler",
            code=lambda_.Code.from_asset("backend/auth/add_user_to_groups"),
            environment={
                **lambda_env,
                "USER_POOL_ID": self.user_pool.user_pool_id,
                "AUTO_JOIN_USER_GROUPS": str(groups),
            },
            layers=[powertools_layer],
        )

        add_to_groups_function.add_permission(
            "CognitoTrigger",
            principal=iam.ServicePrincipal("cognito-idp.amazonaws.com"),
            source_arn=self.user_pool.user_pool_arn,
        )

        self.user_pool.grant(
            add_to_groups_function,
            "cognito-idp:AdminAddUserToGroup",
        )

        trigger_function = lambda_.SingletonFunction(
            self,
            "TriggerFunction",
            uuid="a84c6122-180e-48fc-afaf-f4d65da2b370",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset("custom_resources/cognito_trigger"),
            handler="index.handler",
            environment={
                **lambda_env,
                "USER_POOL_ID": self.user_pool.user_pool_id,
            },
            layers=[powertools_layer],
        )

        self.user_pool.grant(
            trigger_function,
            "cognito-idp:UpdateUserPool",
            "cognito-idp:DescribeUserPool",
        )

        CustomResource(
            self,
            "CognitoTrigger",
            service_token=trigger_function.function_arn,
            properties={
                "Triggers": {
                    "PostConfirmation": add_to_groups_function.function_arn,
                    "PostAuthentication": add_to_groups_function.function_arn,
                },
            },
        )

    def _configure_email_domain_check(
        self,
        domains: List[str],
        powertools_layer: lambda_.ILayerVersion,
        lambda_env: dict,
    ) -> None:
        """
        Configure email domain restriction for signup.

        Args:
            domains: List of allowed email domains
            powertools_layer: AWS Lambda Powertools layer
            lambda_env: Common Lambda environment variables
        """
        check_email_function = lambda_.Function(
            self,
            "CheckEmailDomain",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="check_email_domain.handler",
            code=lambda_.Code.from_asset("backend/auth/check_email_domain"),
            environment={
                **lambda_env,
                "ALLOWED_SIGN_UP_EMAIL_DOMAINS": str(domains),
            },
            layers=[powertools_layer],
        )

        self.user_pool.add_trigger(
            cognito.UserPoolOperation.PRE_SIGN_UP,
            check_email_function,
        )
