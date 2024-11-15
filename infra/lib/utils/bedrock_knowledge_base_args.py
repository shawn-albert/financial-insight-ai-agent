"""
Bedrock Knowledge Base Utility for Financial Insight Agent.

This module provides utilities for configuring and managing Bedrock knowledge bases,
including embeddings, chunking strategies, and analyzers.
"""

from typing import Any, Dict, Optional

from aws_cdk import aws_bedrock as bedrock


def get_embedding_model(embeddings_model: str) -> bedrock.BedrockFoundationModel:
    """
    Get the appropriate Bedrock foundation model for embeddings.

    Args:
        embeddings_model: Name of the embeddings model

    Returns:
        Configured Bedrock foundation model

    Raises:
        ValueError: If the embeddings model is unknown
    """
    model_map = {
        "titan_v2": bedrock.BedrockFoundationModel.TITAN_EMBED_TEXT_V2_1024,
        "cohere_multilingual_v3": bedrock.BedrockFoundationModel.COHERE_EMBED_MULTILINGUAL_V3,
    }

    if embeddings_model not in model_map:
        raise ValueError(f"Unknown embeddings model: {embeddings_model}")

    return model_map[embeddings_model]


def get_parsing_model(parsing_model: str) -> Optional[bedrock.BedrockFoundationModel]:
    """
    Get the appropriate Bedrock foundation model for parsing.

    Args:
        parsing_model: Name of the parsing model

    Returns:
        Configured Bedrock foundation model or None if disabled

    Raises:
        ValueError: If the parsing model is unknown
    """
    model_map = {
        "anthropic.claude-3-sonnet-v1": bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_SONNET_V1_0,
        "anthropic.claude-3-haiku-v1": bedrock.BedrockFoundationModel.ANTHROPIC_CLAUDE_HAIKU_V1_0,
        "disabled": None,
    }

    if parsing_model not in model_map:
        raise ValueError(f"Unknown parsing model: {parsing_model}")

    return model_map[parsing_model]


def get_chunking_strategy(
    strategy: str, embeddings_model: str, options: Optional[Dict[str, Any]] = None
) -> bedrock.ChunkingStrategy:
    """
    Get the appropriate chunking strategy for the knowledge base.

    Args:
        strategy: Name of the chunking strategy
        embeddings_model: Name of the embeddings model
        options: Additional configuration options

    Returns:
        Configured chunking strategy

    Raises:
        ValueError: If the chunking strategy is unknown
    """
    if strategy == "default":
        return bedrock.ChunkingStrategy.DEFAULT

    if strategy == "fixed_size":
        if options and "max_tokens" in options and "overlap_percentage" in options:
            return bedrock.ChunkingStrategy.fixed_size(
                {
                    "max_tokens": options["max_tokens"],
                    "overlap_percentage": options["overlap_percentage"],
                }
            )
        return bedrock.ChunkingStrategy.FIXED_SIZE

    if strategy == "hierarchical":
        if (
            options
            and "overlap_tokens" in options
            and "max_parent_token_size" in options
            and "max_child_token_size" in options
        ):
            return bedrock.ChunkingStrategy.hierarchical(
                {
                    "overlap_tokens": options["overlap_tokens"],
                    "max_parent_token_size": options["max_parent_token_size"],
                    "max_child_token_size": options["max_child_token_size"],
                }
            )
        return (
            bedrock.ChunkingStrategy.HIERARCHICAL_TITAN
            if embeddings_model == "titan_v2"
            else bedrock.ChunkingStrategy.HIERARCHICAL_COHERE
        )

    if strategy == "semantic":
        if (
            options
            and "max_tokens" in options
            and "buffer_size" in options
            and "breakpoint_percentile_threshold" in options
        ):
            return bedrock.ChunkingStrategy.semantic(
                {
                    "max_tokens": options["max_tokens"],
                    "buffer_size": options["buffer_size"],
                    "breakpoint_percentile_threshold": options[
                        "breakpoint_percentile_threshold"
                    ],
                }
            )
        return bedrock.ChunkingStrategy.SEMANTIC

    if strategy == "none":
        return bedrock.ChunkingStrategy.NONE

    raise ValueError(f"Unknown chunking strategy: {strategy}")


def get_analyzer(analyzer_config: Dict[str, Any]) -> Optional[bedrock.Analyzer]:
    """
    Get the OpenSearch analyzer configuration.

    Args:
        analyzer_config: Analyzer configuration dictionary

    Returns:
        Configured analyzer or None if invalid configuration

    Raises:
        ValueError: If analyzer components are unknown
    """
    if not analyzer_config or "character_filters" not in analyzer_config:
        return None

    character_filters = []
    for filter_config in analyzer_config["character_filters"].get("L", []):
        filter_type = filter_config.get("S")
        if filter_type == "icu_normalizer":
            character_filters.append(bedrock.CharacterFilterType.ICU_NORMALIZER)
        else:
            raise ValueError(f"Unknown character filter: {filter_type}")

    if not analyzer_config.get("tokenizer") or not analyzer_config["tokenizer"].get(
        "S"
    ):
        raise ValueError("Tokenizer is not defined")

    tokenizer_type = analyzer_config["tokenizer"]["S"]
    tokenizer_map = {
        "kuromoji_tokenizer": bedrock.TokenizerType.KUROMOJI_TOKENIZER,
        "icu_tokenizer": bedrock.TokenizerType.ICU_TOKENIZER,
    }
    if tokenizer_type not in tokenizer_map:
        raise ValueError(f"Unknown tokenizer: {tokenizer_type}")
    tokenizer = tokenizer_map[tokenizer_type]

    token_filters = []
    for filter_config in analyzer_config.get("token_filters", {}).get("L", []):
        filter_type = filter_config.get("S")
        filter_map = {
            "kuromoji_baseform": bedrock.TokenFilterType.KUROMOJI_BASEFORM,
            "kuromoji_part_of_speech": bedrock.TokenFilterType.KUROMOJI_PART_OF_SPEECH,
            "kuromoji_stemmer": bedrock.TokenFilterType.KUROMOJI_STEMMER,
            "cjk_width": bedrock.TokenFilterType.CJK_WIDTH,
            "ja_stop": bedrock.TokenFilterType.JA_STOP,
            "lowercase": bedrock.TokenFilterType.LOWERCASE,
            "icu_folding": bedrock.TokenFilterType.ICU_FOLDING,
        }
        if filter_type not in filter_map:
            raise ValueError(f"Unknown token filter: {filter_type}")
        token_filters.append(filter_map[filter_type])

    return bedrock.Analyzer(
        character_filters=character_filters,
        tokenizer=tokenizer,
        token_filters=token_filters,
    )
