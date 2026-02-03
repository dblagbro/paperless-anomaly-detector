"""Configuration management using Pydantic settings."""
import os
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Paperless API configuration
    paperless_api_base_url: str = Field(
        default="http://paperless-web:8000",
        description="Base URL for Paperless-ngx API"
    )
    paperless_public_url: str = Field(
        default="https://www.voipguru.org/paperless",
        description="Public URL for Paperless-ngx web interface"
    )
    paperless_api_token: str = Field(
        ...,
        description="API token for Paperless-ngx authentication"
    )

    # LLM configuration (optional)
    llm_provider: Optional[str] = Field(
        default=None,
        description="LLM provider: 'anthropic', 'openai', or None to disable"
    )
    llm_api_key: Optional[str] = Field(
        default=None,
        description="API key for LLM provider"
    )
    llm_model: str = Field(
        default="claude-3-5-sonnet-20241022",
        description="LLM model to use"
    )
    llm_max_tokens: int = Field(
        default=1000,
        description="Maximum tokens for LLM responses"
    )

    # Polling configuration
    polling_interval: int = Field(
        default=300,
        description="Interval in seconds between Paperless API polls"
    )
    batch_size: int = Field(
        default=10,
        description="Number of documents to process per batch"
    )

    # Database configuration
    database_url: str = Field(
        default="sqlite:///data/anomaly_detector.db",
        description="Database connection URL"
    )

    # Detection thresholds
    balance_tolerance: float = Field(
        default=0.01,
        description="Tolerance for balance mismatches (in currency units)"
    )
    layout_variance_threshold: float = Field(
        default=0.3,
        description="Threshold for layout irregularity detection (0-1)"
    )

    # Web UI configuration
    web_host: str = Field(default="0.0.0.0", description="Web server host")
    web_port: int = Field(default=8050, description="Web server port")

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    @validator("paperless_api_token")
    def validate_token(cls, v):
        """Ensure token is not empty."""
        if not v or v.strip() == "":
            raise ValueError("PAPERLESS_API_TOKEN must be set")
        return v

    @validator("llm_provider")
    def validate_llm_provider(cls, v):
        """Validate LLM provider value."""
        if v and v not in ["anthropic", "openai"]:
            raise ValueError("llm_provider must be 'anthropic' or 'openai'")
        return v

    class Config:
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()
