"""
Authentication Construct Implementation for Financial Insight Agent.

This module implements authentication and authorization using Amazon Cognito,
supporting multiple identity providers, user groups, and custom triggers
for user management.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

from aws_cdk import CfnOutput, CustomResource, Duration, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_secretsmanager as secretsmanager
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
            compatible_architectures=[lambda_.Architecture.ARM_64],
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
            handler="index.handler",
            code=lambda_.Code.from_asset(
                os.path.join(PROJECT_ROOT, "backend", "auth", "add_user_to_groups")
            ),
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
            code=lambda_.Code.from_asset(
                os.path.join(PROJECT_ROOT, "backend", "auth", "cognito_trigger")
            ),
            handler="index.handler",
            timeout=Duration.minutes(15),
            memory_size=512,
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
            handler="index.handler",
            code=lambda_.Code.from_asset(
                os.path.join(PROJECT_ROOT, "backend", "auth", "check_email_domain")
            ),
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

    def _configure_client_props(self, props: AuthProps) -> dict:
        """
        Configure Cognito user pool client properties.

        Args:
            props: Authentication properties

        Returns:
            Dictionary of client configuration properties
        """
        default_props = {
            "auth_flows": cognito.AuthFlow(
                user_password=True,
                user_srp=True,
            ),
        }

        if not any(props.identity_providers):
            return default_props

        return {
            **default_props,
            "o_auth": cognito.OAuthSettings(
                callback_urls=[props.origin],
                logout_urls=[props.origin],
            ),
            "supported_identity_providers": self._get_supported_providers(
                props.identity_providers
            ),
        }

    def _get_supported_providers(
        self, providers: List[dict]
    ) -> List[cognito.UserPoolClientIdentityProvider]:
        """
        Get list of supported identity providers.

        Args:
            providers: List of identity provider configurations

        Returns:
            List of supported Cognito identity providers
        """
        supported_providers = []

        for provider in providers:
            if provider["service"] == "google":
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.GOOGLE
                )
            elif provider["service"] == "facebook":
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.FACEBOOK
                )
            elif provider["service"] == "amazon":
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.AMAZON
                )
            elif provider["service"] == "apple":
                supported_providers.append(cognito.UserPoolClientIdentityProvider.APPLE)
            elif provider["service"] == "oidc":
                if not provider.get("service_name"):
                    raise ValueError("service_name required for OIDC provider")
                supported_providers.append(
                    cognito.UserPoolClientIdentityProvider.custom(
                        provider["service_name"]
                    )
                )

        if providers:
            supported_providers.append(cognito.UserPoolClientIdentityProvider.COGNITO)

        return supported_providers

    def _configure_identity_providers(self, props: AuthProps) -> None:
        """
        Configure external identity providers.

        Args:
            props: Authentication properties
        """
        for provider in props.identity_providers:
            secret = secretsmanager.Secret.from_secret_name_v2(
                self,
                f"Secret-{provider['secret_name']}",
                provider["secret_name"],
            )

            client_id = secret.secret_value_from_json("clientId").to_string()
            client_secret = secret.secret_value_from_json("clientSecret")

            if provider["service"] == "google":
                google_provider = cognito.UserPoolIdentityProviderGoogle(
                    self,
                    f"GoogleProvider-{provider['secret_name']}",
                    user_pool=self.user_pool,
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=["openid", "email"],
                    attribute_mapping={
                        "email": cognito.ProviderAttribute.GOOGLE_EMAIL,
                    },
                )
                self.client.node.add_dependency(google_provider)

            elif provider["service"] == "oidc":
                issuer_url = secret.secret_value_from_json("issuerUrl").to_string()
                oidc_provider = cognito.UserPoolIdentityProviderOidc(
                    self,
                    f"OidcProvider-{provider['secret_name']}",
                    user_pool=self.user_pool,
                    client_id=client_id,
                    client_secret=client_secret.to_string(),
                    issuer_url=issuer_url,
                    attribute_mapping={
                        "email": cognito.ProviderAttribute.other("EMAIL"),
                    },
                    scopes=["openid", "email"],
                )
                self.client.node.add_dependency(oidc_provider)

    def _create_user_groups(self) -> None:
        """
        Create default user groups in the Cognito user pool.
        """
        cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            group_name="Admin",
            user_pool_id=self.user_pool.user_pool_id,
        )

        cognito.CfnUserPoolGroup(
            self,
            "CreatingBotAllowedGroup",
            group_name="CreatingBotAllowed",
            user_pool_id=self.user_pool.user_pool_id,
        )

        cognito.CfnUserPoolGroup(
            self,
            "PublishAllowedGroup",
            group_name="PublishAllowed",
            user_pool_id=self.user_pool.user_pool_id,
        )

    def _create_outputs(self) -> None:
        """
        Create CloudFormation outputs for authentication resources.
        """
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="ID of the Cognito user pool",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.client.user_pool_client_id,
            description="ID of the Cognito user pool client",
        )
