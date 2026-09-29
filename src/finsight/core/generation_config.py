"""Opt-in secret settings, separate from public generation payloads."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from finsight.domain.generation import GenerationPolicy


class GenerationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINSIGHT_GENERATION_", env_file=None, extra="forbid", frozen=True,
    )

    enabled: bool = False
    model: Literal["deepseek-flash"] = "deepseek-flash"
    api_key: SecretStr = Field(default=SecretStr(""), repr=False, exclude=True)
    max_attempts: int = 2
    max_daily_attempts: int = 20
    max_output_tokens: int = 512
    request_timeout_seconds: int = 20
    total_timeout_seconds: int = 45

    @model_validator(mode="after")
    def validate_limits(self):
        self.policy()
        return self

    def policy(self) -> GenerationPolicy:
        return GenerationPolicy(**self.model_dump(exclude={"model"}))


def load_generation_settings(secret_file: Path | None = None) -> GenerationSettings:
    # Never log settings validation exceptions: they may include rejected secret input.
    try:
        if secret_file is not None and not secret_file.is_file():
            raise ValueError("missing configuration")
        return GenerationSettings(_env_file=secret_file)
    except Exception:  # noqa: BLE001 - conceal any configuration input in diagnostics
        raise ValueError("generation_configuration_invalid") from None
