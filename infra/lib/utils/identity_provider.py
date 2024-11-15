"""
Identity Provider Utility for Financial Insight Agent.

This module provides utilities for managing and configuring identity providers
for Cognito user pools.
"""

from typing import List, Optional, TypedDict

from aws_cdk import aws_cognito as cognito


class IdentityProviderConfig(TypedDict):
    """
    Configuration for identity providers.

    Attributes:
        service: Service name for social providers
        service_name: Service name for OIDC (required when service is "oidc")
        secret_name: Name of the secret in Secrets Manager
    """

    service: str
    service_name: Optional[str]
    secret_name: str


class IdentityProviderService:
    """
    Service for managing identity provider configurations.

    This class handles the configuration and management of various identity
    providers including social logins and OIDC providers.
    """

    def __init__(self, identity_providers: List[IdentityProviderConfig]) -> None:
        """
        Initialize the identity provider service.

        Args:
            identity_providers: List of identity provider configurations
        """
        self._providers = identity_providers

    def exists(self) -> bool:
        """
        Check if any identity providers are configured.

        Returns:
            True if identity providers exist, False otherwise
        """
        return len(self._providers) > 0

    def get_providers(self) -> List[IdentityProviderConfig]:
        """
        Get list of configured identity providers.

        Returns:
            List of identity provider configurations
        """
        return self._providers if self.exists() else []

    def get_supported_providers(self) -> List[cognito.UserPoolClientIdentityProvider]:
        """
        Get list of supported identity providers for Cognito.

        Returns:
            List of Cognito identity providers
        """
        providers = self.get_providers()
        if not providers:
            return []

        cognito_providers = []
        for provider in providers:
            if provider["service"] == "google":
                cognito_providers.append(cognito.UserPoolClientIdentityProvider.GOOGLE)
            elif provider["service"] == "facebook":
                cognito_providers.append(
                    cognito.UserPoolClientIdentityProvider.FACEBOOK
                )
            elif provider["service"] == "amazon":
                cognito_providers.append(cognito.UserPoolClientIdentityProvider.AMAZON)
            elif provider["service"] == "apple":
                cognito_providers.append(cognito.UserPoolClientIdentityProvider.APPLE)
            elif provider["service"] == "oidc":
                if not provider.get("service_name"):
                    raise ValueError("service_name required for OIDC provider")
                cognito_providers.append(
                    cognito.UserPoolClientIdentityProvider.custom(
                        provider["service_name"]
                    )
                )

        if providers:
            cognito_providers.append(cognito.UserPoolClientIdentityProvider.COGNITO)

        return cognito_providers

    def get_social_providers(self) -> str:
        """
        Get comma-separated list of social provider names.

        Returns:
            Comma-separated list of provider names
        """
        return ",".join(
            provider["service"]
            for provider in self.get_providers()
            if provider["service"] != "oidc"
        )

    def has_custom_provider(self) -> bool:
        """
        Check if OIDC provider is configured.

        Returns:
            True if OIDC provider exists, False otherwise
        """
        return any(provider["service"] == "oidc" for provider in self.get_providers())

    def get_custom_provider_name(self) -> Optional[str]:
        """
        Get name of configured OIDC provider.

        Returns:
            OIDC provider name if configured, None otherwise
        """
        for provider in self.get_providers():
            if provider["service"] == "oidc":
                return provider.get("service_name")
        return None
