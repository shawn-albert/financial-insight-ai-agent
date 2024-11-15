"""
Bedrock Custom Bot Stack Implementation for Financial Insight Agent.

This module implements the infrastructure for custom chatbots using Amazon Bedrock,
including knowledge bases, vector stores, and content filtering guardrails.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

from aws_cdk import CfnOutput, Stack, StackProps
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_s3 as s3
from constructs import Construct
from lib.utils.bedrock_guardrails import get_threshold


@dataclass
class BedrockGuardrailProps:
    """
    Properties for Bedrock guardrail configuration.

    Attributes:
        is_guardrail_enabled: Whether guardrails are enabled
        hate_threshold: Threshold for hate content
        insults_threshold: Threshold for insults
        sexual_threshold: Threshold for sexual content
        violence_threshold: Threshold for violence
        misconduct_threshold: Threshold for misconduct
        grounding_threshold: Threshold for grounding
        relevance_threshold: Threshold for relevance
        guardrail_arn: ARN of existing guardrail
        guardrail_version: Version of existing guardrail
    """

    is_guardrail_enabled: Optional[bool] = None
    hate_threshold: Optional[int] = None
    insults_threshold: Optional[int] = None
    sexual_threshold: Optional[int] = None
    violence_threshold: Optional[int] = None
    misconduct_threshold: Optional[int] = None
    grounding_threshold: Optional[int] = None
    relevance_threshold: Optional[int] = None
    guardrail_arn: Optional[str] = None
    guardrail_version: Optional[int] = None


@dataclass
class BedrockCustomBotStackProps(StackProps):
    """
    Properties for Bedrock Custom Bot Stack configuration.

    Attributes:
        owner_user_id: ID of the bot owner
        bot_id: Unique identifier for the bot
        embeddings_model: Model for generating embeddings
        parsing_model: Model for parsing content
        bedrock_document_bucket_name: Name of document storage bucket
        chunking_strategy: Strategy for chunking content
        existing_s3_urls: List of existing S3 URLs
        max_tokens: Maximum tokens per chunk
        instruction: Custom instruction for the bot
        analyzer: OpenSearch analyzer configuration
        overlap_percentage: Percentage of overlap between chunks
        guardrail: Configuration for content filtering
        use_standby_replicas: Whether to use standby replicas
    """

    owner_user_id: str
    bot_id: str
    embeddings_model: bedrock.BedrockFoundationModel
    parsing_model: Optional[bedrock.BedrockFoundationModel]
    bedrock_document_bucket_name: str
    chunking_strategy: bedrock.ChunkingStrategy
    existing_s3_urls: List[str]
    max_tokens: Optional[int]
    instruction: Optional[str]
    analyzer: Optional[bedrock.Analyzer]
    overlap_percentage: Optional[float]
    guardrail: Optional[BedrockGuardrailProps]
    use_standby_replicas: Optional[bool]


class BedrockCustomBotStack(Stack):
    """
    Bedrock Custom Bot Stack for the Financial Insight Agent.

    This stack creates and manages custom bot resources including:
    - Vector collections and indexes
    - Knowledge bases
    - Content filtering guardrails
    - Document sources and data ingestion
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        props: BedrockCustomBotStackProps,
    ) -> None:
        """
        Initialize the Bedrock Custom Bot stack.

        Args:
            scope: CDK scope for resource creation
            construct_id: Unique identifier for the stack
            props: Configuration properties for the custom bot
        """
        super().__init__(scope, construct_id, props)

        doc_buckets_and_prefixes = self._setup_buckets_and_prefixes(props)

        vector_collection = self._create_vector_collection(props)
        vector_index = self._create_vector_index(props, vector_collection)

        knowledge_base = self._create_knowledge_base(
            props, vector_collection, vector_index
        )

        self._create_data_sources(props, knowledge_base, doc_buckets_and_prefixes)

        if props.guardrail and props.guardrail.is_guardrail_enabled:
            self._create_guardrails(props)

        self._create_outputs(props, knowledge_base)

    def _setup_buckets_and_prefixes(
        self,
        props: BedrockCustomBotStackProps,
    ) -> List[Dict[str, str]]:
        """
        Set up S3 buckets and prefixes for document storage.

        Args:
            props: Stack properties

        Returns:
            List of bucket and prefix configurations
        """
        result = []

        result.append(
            {
                "bucket": s3.Bucket.from_bucket_name(
                    self,
                    props.bedrock_document_bucket_name,
                    props.bedrock_document_bucket_name,
                ),
                "prefix": f"{props.owner_user_id}/{props.bot_id}/documents/",
            }
        )

        if props.existing_s3_urls:
            for url in props.existing_s3_urls:
                bucket_name, prefix = self._parse_s3_url(url)
                result.append(
                    {
                        "bucket": s3.Bucket.from_bucket_name(
                            self,
                            bucket_name,
                            bucket_name,
                        ),
                        "prefix": prefix,
                    }
                )

        return result

    def _create_vector_collection(
        self,
        props: BedrockCustomBotStackProps,
    ) -> bedrock.VectorCollection:
        """
        Create vector collection for embeddings storage.

        Args:
            props: Stack properties

        Returns:
            Configured vector collection
        """
        return bedrock.VectorCollection(
            self,
            "KBVectors",
            collection_name=f"kb-{props.bot_id[:20].lower()}",
            standby_replicas=(
                bedrock.VectorCollectionStandbyReplicas.ENABLED
                if props.use_standby_replicas
                else bedrock.VectorCollectionStandbyReplicas.DISABLED
            ),
        )

    def _create_vector_index(
        self,
        props: BedrockCustomBotStackProps,
        vector_collection: bedrock.VectorCollection,
    ) -> bedrock.VectorIndex:
        """
        Create vector index for similarity search.

        Args:
            props: Stack properties
            vector_collection: Vector collection to index

        Returns:
            Configured vector index
        """
        return bedrock.VectorIndex(
            self,
            "KBIndex",
            collection=vector_collection,
            index_name="bedrock-knowledge-base-default-index",
            vector_field="bedrock-knowledge-base-default-vector",
            vector_dimensions=props.embeddings_model.vector_dimensions,
            mappings=[
                bedrock.VectorIndexMapping(
                    mapping_field="AMAZON_BEDROCK_TEXT_CHUNK",
                    data_type="text",
                    filterable=True,
                ),
                bedrock.VectorIndexMapping(
                    mapping_field="AMAZON_BEDROCK_METADATA",
                    data_type="text",
                    filterable=False,
                ),
            ],
            analyzer=props.analyzer,
        )

    def _create_knowledge_base(
        self,
        props: BedrockCustomBotStackProps,
        vector_collection: bedrock.VectorCollection,
        vector_index: bedrock.VectorIndex,
    ) -> bedrock.KnowledgeBase:
        """
        Create knowledge base for the custom bot.

        Args:
            props: Stack properties
            vector_collection: Vector collection for storage
            vector_index: Vector index for search

        Returns:
            Configured knowledge base
        """
        return bedrock.KnowledgeBase(
            self,
            "KB",
            embeddings_model=props.embeddings_model,
            vector_store=vector_collection,
            vector_index=vector_index,
            instruction=props.instruction,
        )

    def _create_data_sources(
        self,
        props: BedrockCustomBotStackProps,
        knowledge_base: bedrock.KnowledgeBase,
        buckets_and_prefixes: List[Dict[str, str]],
    ) -> None:
        """
        Create data sources for the knowledge base.

        Args:
            props: Stack properties
            knowledge_base: Target knowledge base
            buckets_and_prefixes: List of S3 bucket and prefix configurations
        """
        for idx, config in enumerate(buckets_and_prefixes):
            bucket = config["bucket"]
            prefix = config["prefix"]
            bucket.grant_read(knowledge_base.role)

            bedrock.S3DataSource(
                self,
                f"DataSource{idx}",
                bucket=bucket,
                knowledge_base=knowledge_base,
                data_source_name=bucket.bucket_name,
                chunking_strategy=props.chunking_strategy,
                parsing_strategy=(
                    bedrock.ParsingStrategy.foundation_model(
                        {
                            "parsing_model": props.parsing_model.as_imodel(self),
                        }
                    )
                    if props.parsing_model
                    else None
                ),
                inclusion_prefixes=[prefix] if prefix else None,
            )

    def _create_guardrails(
        self,
        props: BedrockCustomBotStackProps,
    ) -> None:
        """
        Create content filtering guardrails.

        Args:
            props: Stack properties
        """
        if not props.guardrail:
            return

        content_filters = []
        grounding_filters = []

        if props.guardrail.hate_threshold and props.guardrail.hate_threshold > 0:
            content_filters.append(
                bedrock.CfnGuardrail.ContentFiltersConfigProperty(
                    input_strength=get_threshold(props.guardrail.hate_threshold),
                    output_strength=get_threshold(props.guardrail.hate_threshold),
                    filter_type="HATE",
                )
            )

        if props.guardrail.insults_threshold and props.guardrail.insults_threshold > 0:
            content_filters.append(
                bedrock.CfnGuardrail.ContentFiltersConfigProperty(
                    input_strength=get_threshold(props.guardrail.insults_threshold),
                    output_strength=get_threshold(props.guardrail.insults_threshold),
                    filter_type="INSULTS",
                )
            )

        if props.guardrail.sexual_threshold and props.guardrail.sexual_threshold > 0:
            content_filters.append(
                bedrock.CfnGuardrail.ContentFiltersConfigProperty(
                    input_strength=get_threshold(props.guardrail.sexual_threshold),
                    output_strength=get_threshold(props.guardrail.sexual_threshold),
                    filter_type="SEXUAL",
                )
            )

        if (
            props.guardrail.violence_threshold
            and props.guardrail.violence_threshold > 0
        ):
            content_filters.append(
                bedrock.CfnGuardrail.ContentFiltersConfigProperty(
                    input_strength=get_threshold(props.guardrail.violence_threshold),
                    output_strength=get_threshold(props.guardrail.violence_threshold),
                    filter_type="VIOLENCE",
                )
            )

        if (
            props.guardrail.misconduct_threshold
            and props.guardrail.misconduct_threshold > 0
        ):
            content_filters.append(
                bedrock.CfnGuardrail.ContentFiltersConfigProperty(
                    input_strength=get_threshold(props.guardrail.misconduct_threshold),
                    output_strength=get_threshold(props.guardrail.misconduct_threshold),
                    filter_type="MISCONDUCT",
                )
            )

        if (
            props.guardrail.grounding_threshold
            and props.guardrail.grounding_threshold > 0
        ):
            grounding_filters.append(
                bedrock.CfnGuardrail.GroundingFiltersConfigProperty(
                    threshold=props.guardrail.grounding_threshold,
                    filter_type="GROUNDING",
                )
            )

        if (
            props.guardrail.relevance_threshold
            and props.guardrail.relevance_threshold > 0
        ):
            grounding_filters.append(
                bedrock.CfnGuardrail.GroundingFiltersConfigProperty(
                    threshold=props.guardrail.relevance_threshold,
                    filter_type="RELEVANCE",
                )
            )

        if content_filters or grounding_filters:
            guardrail = bedrock.CfnGuardrail(
                self,
                "Guardrail",
                name=props.bot_id,
                blocked_input_messaging="This input message is blocked",
                blocked_outputs_messaging="This output message is blocked",
                content_policy_config=(
                    bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                        filters_config=content_filters
                    )
                    if content_filters
                    else None
                ),
                contextual_grounding_policy_config=(
                    bedrock.CfnGuardrail.ContextualGroundingPolicyConfigProperty(
                        filters_config=grounding_filters
                    )
                    if grounding_filters
                    else None
                ),
            )

            CfnOutput(
                self,
                "GuardrailArn",
                value=guardrail.attr_guardrail_arn,
            )
            CfnOutput(
                self,
                "GuardrailVersion",
                value=guardrail.attr_version,
            )

    def _create_outputs(
        self,
        props: BedrockCustomBotStackProps,
        knowledge_base: bedrock.KnowledgeBase,
    ) -> None:
        """
        Create CloudFormation outputs.

        Args:
            props: Stack properties
            knowledge_base: Created knowledge base
        """
        CfnOutput(
            self,
            "KnowledgeBaseId",
            value=knowledge_base.knowledge_base_id,
        )
        CfnOutput(
            self,
            "KnowledgeBaseArn",
            value=knowledge_base.knowledge_base_arn,
        )
        CfnOutput(
            self,
            "OwnerUserId",
            value=props.owner_user_id,
        )
        CfnOutput(
            self,
            "BotId",
            value=props.bot_id,
        )

    def _parse_s3_url(self, url: str) -> tuple[str, str]:
        """
        Parse S3 URL into bucket name and prefix.

        Args:
            url: S3 URL to parse

        Returns:
            Tuple of bucket name and prefix

        Raises:
            ValueError: If URL format is invalid
        """
        if not url.startswith("s3://"):
            raise ValueError(f"Invalid S3 URL format: {url}")

        parts = url.replace("s3://", "").split("/")
        if len(parts) < 1:
            raise ValueError(f"Invalid S3 URL format: {url}")

        bucket_name = parts[0]
        prefix = "/".join(parts[1:])

        return bucket_name, prefix
