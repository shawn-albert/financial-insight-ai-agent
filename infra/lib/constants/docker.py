"""
Docker-related constants for Financial Insight Agent.

This module defines constants used in Docker image building and deployment,
specifically patterns for files and directories to exclude from Docker contexts.
"""

from typing import List

DOCKER_EXCLUDE_PATTERNS: List[str] = [
    ".mypy_cache",
    ".venv",
    "test",
    "tests",
    "node_modules",
    "dist",
    "dev-dist",
    ".env",
    ".env.local",
]
