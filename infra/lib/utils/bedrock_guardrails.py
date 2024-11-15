"""
Bedrock Guardrails Utility for Financial Insight Agent.

This module provides utilities for configuring and managing Bedrock guardrails
and content filtering thresholds.
"""

from enum import Enum
from typing import Optional


class Threshold(str, Enum):
    """
    Threshold levels for Bedrock content filtering.

    Values represent different sensitivity levels for content filtering.
    """

    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


def get_threshold(input_param: Optional[int]) -> Threshold:
    """
    Convert numeric threshold input to corresponding Threshold enum value.

    Args:
        input_param: Numeric threshold value (0-3)

    Returns:
        Corresponding Threshold enum value
    """
    if input_param is None:
        return Threshold.NONE

    threshold_map = {
        0: Threshold.NONE,
        1: Threshold.LOW,
        2: Threshold.MEDIUM,
        3: Threshold.HIGH,
    }

    return threshold_map.get(input_param, Threshold.NONE)
