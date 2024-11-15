"""
Regional Resources Stack for Financial Insight Agent.

This module implements resources that must be deployed in the same region
as Amazon Bedrock. This includes document buckets and other region-specific
resources required for Bedrock integration.
"""

from dataclasses import dataclass

from aws_cdk import CfnOutput, RemovalPolicy, Stack, StackProps
from aws_cdk import aws_s3 as s3
from constructs import Construct


@dataclass
class RegionalResourcesStackProps(StackProps):
    """
    Properties for the Regional Resources Stack.

    Attributes:
        cross_region_references: Flag to enable cross-region resource references
    """

    cross_region_references: bool


class RegionalResourcesStack(Stack):
    """
    Stack containing resources that must be deployed in the Bedrock region.

    This stack creates and manages resources that need to be in the same region
    as Amazon Bedrock, particularly storage resources for documents and other
    artifacts used by the knowledge base.

    Attributes:
        document_bucket: S3 bucket for storing documents used by Bedrock
        access_log_bucket: S3 bucket for storing access logs
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cross_region_references: bool = False,
        **kwargs,
    ) -> None:
        """
        Initialize the Regional Resources Stack.

        Args:
            scope: The CDK scope for resource creation
            construct_id: Unique identifier for the stack
            cross_region_references: Flag to enable cross-region references
            **kwargs: Additional stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        region_prefix = Stack.of(self).region

        self.access_log_bucket = s3.Bucket(
            self,
            f"{region_prefix}AccessLogBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            auto_delete_objects=True,
        )

        self.document_bucket = s3.Bucket(
            self,
            f"{region_prefix}DocumentBucket",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
            auto_delete_objects=True,
            server_access_logs_bucket=self.access_log_bucket,
            server_access_logs_prefix="DocumentBucket",
        )

        CfnOutput(
            self,
            "DocumentBucketName",
            value=self.document_bucket.bucket_name,
            description="Name of the S3 bucket for storing documents",
        )
