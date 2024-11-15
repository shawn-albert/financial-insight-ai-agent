import logging

import aws_cdk as cdk
from aws_cdk import aws_athena as athena
from aws_cdk import aws_glue as glue
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_s3 as s3
from constructs import Construct

logger = logging.getLogger(__name__)


class FinancialInsightStack(cdk.Stack):
    """
    Core infrastructure stack for Financial Insight AI Agent.
    Implements secure data storage, analytics capabilities, and AI processing infrastructure.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        """
        Initialize Financial Insight infrastructure components.

        Args:
            scope: Parent construct scope
            construct_id: Unique identifier for this stack
            kwargs: Additional AWS CDK stack properties
        """
        super().__init__(scope, construct_id, **kwargs)

        self.logging_bucket = self._create_logging_bucket()
        self.athena_kms_key = self._create_athena_kms_key()
        self.athena_results_bucket = self._create_athena_results_bucket()
        self.lambda_code_bucket = self._create_lambda_code_bucket()
        self.query_staging_bucket = self._create_query_staging_bucket()

        self.workgroup = self._create_athena_workgroup()
        self.database = self._create_analytics_database()

    def _create_logging_bucket(self) -> s3.Bucket:
        """
        Creates a centralized logging bucket with appropriate security controls.

        Returns:
            S3 Bucket configured for secure logging
        """
        bucket = s3.Bucket(
            self,
            "LoggingBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
        )

        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:*"],
                resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
                conditions={"Bool": {"aws:SecureTransport": False}},
            )
        )
        return bucket

    def _create_athena_kms_key(self) -> kms.Key:
        """
        Creates KMS key for Athena query results encryption.

        Returns:
            KMS key configured for Athena encryption
        """
        return kms.Key(
            self,
            "AthenaKMSKey",
            description="KMS Key for encrypting Athena query results",
            enable_key_rotation=True,
        )

    def _create_athena_results_bucket(self) -> s3.Bucket:
        """
        Creates secure bucket for Athena query results with logging and encryption.

        Returns:
            S3 Bucket configured for Athena results
        """
        bucket = s3.Bucket(
            self,
            "AthenaQueryResultBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.KMS,
            encryption_key=self.athena_kms_key,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="AthenaQueryResultBucket-logs/",
        )

        self._add_secure_transport_policy(bucket)
        return bucket

    def _create_query_staging_bucket(self) -> s3.Bucket:
        """
        Creates staging bucket for query processing with logging enabled.

        Returns:
            S3 Bucket configured for query staging
        """
        bucket = s3.Bucket(
            self,
            "QueryStagingBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="QueryStagingBucket-logs/",
        )

        self._add_secure_transport_policy(bucket)
        return bucket

    def _create_lambda_code_bucket(self) -> s3.Bucket:
        """
        Creates bucket for Lambda function code storage with logging enabled.

        Returns:
            S3 Bucket configured for Lambda code storage
        """
        bucket = s3.Bucket(
            self,
            "LambdaZipsBucket",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            server_access_logs_bucket=self.logging_bucket,
            server_access_logs_prefix="LambdaZipsBucket-logs/",
        )

        self._add_secure_transport_policy(bucket)
        return bucket

    def _create_athena_workgroup(self) -> athena.CfnWorkGroup:
        """
        Creates Athena workgroup with enforced configuration and encryption.

        Returns:
            Configured Athena workgroup
        """
        return athena.CfnWorkGroup(
            self,
            "AthenaWorkGroup",
            name="fsi-workgroup",
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                enforce_work_group_configuration=True,
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    encryption_configuration=athena.CfnWorkGroup.EncryptionConfigurationProperty(
                        encryption_option="SSE_KMS", kms_key=self.athena_kms_key.key_arn
                    ),
                    output_location=f"s3://{self.athena_results_bucket.bucket_name}/query-results/",
                ),
            ),
        )

    def _create_analytics_database(self) -> glue.CfnDatabase:
        """
        Creates Glue database for stock price analytics.

        Returns:
            Configured Glue database
        """
        return glue.CfnDatabase(
            self,
            "BlogStockPricesDB",
            catalog_id=self.account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(
                name="blog-stock-prices-db",
                description="Database for Stock information",
            ),
        )

    def _add_secure_transport_policy(self, bucket: s3.Bucket) -> None:
        """
        Adds secure transport policy to S3 bucket.

        Args:
            bucket: S3 bucket to apply secure transport policy to
        """
        bucket.add_to_resource_policy(
            iam.PolicyStatement(
                effect=iam.Effect.DENY,
                principals=[iam.AnyPrincipal()],
                actions=["s3:*"],
                resources=[bucket.bucket_arn, f"{bucket.bucket_arn}/*"],
                conditions={"Bool": {"aws:SecureTransport": False}},
            )
        )
