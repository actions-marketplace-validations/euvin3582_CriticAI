"""Configuration loading from environment variables.

All action inputs are passed as INPUT_* environment variables by the
composite action in action.yml. This module reads them once at startup
and exposes them as typed, validated fields on a frozen dataclass.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    """Immutable configuration for a single CriticAI run."""

    # GitHub
    github_token: str
    repository: str  # owner/repo
    pr_number: str

    # AWS credentials
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str

    # Model selection
    model: str
    fallback_model: str  # empty string = disabled
    max_tokens: int

    # Review behavior
    prompt: str
    language: str
    title: str
    temperature: float
    top_p: float
    home_directory: str  # path prefix filter; empty = review all files
    max_input_chars: int  # max chars for the diff before truncation kicks in

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from INPUT_* environment variables."""
        return cls(
            github_token=os.environ["INPUT_GITHUB_TOKEN"],
            repository=os.environ["INPUT_GITHUB_REPOSITORY"],
            pr_number=os.environ["INPUT_PR_NUMBER"],
            aws_access_key_id=os.environ["INPUT_AWS_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["INPUT_AWS_SECRET_ACCESS_KEY"],
            aws_region=os.environ["INPUT_AWS_REGION"],
            model=os.environ["INPUT_MODEL"],
            fallback_model=os.environ.get("INPUT_FALLBACK_MODEL", "").strip(),
            max_tokens=int(os.environ["INPUT_MAX_TOKENS"]),
            prompt=os.environ["INPUT_PROMPT"],
            language=os.environ["INPUT_LANGUAGE"],
            title=os.environ["INPUT_TITLE"],
            temperature=float(os.environ["INPUT_TEMPERATURE"]),
            top_p=float(os.environ["INPUT_TOP_P"]),
            home_directory=os.environ.get("INPUT_HOME_DIRECTORY", ""),
            max_input_chars=int(os.environ.get("INPUT_MAX_INPUT_CHARS", "150000")),
        )
