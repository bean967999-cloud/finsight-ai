"""Read-only local readiness check before loading a large embedding model."""

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

from finsight.domain.embedding import EmbeddingSpec


@dataclass(frozen=True, slots=True)
class EmbeddingReadiness:
    model_directory: Path
    model_files_present: bool
    installed_packages: dict[str, bool]
    actual_dimension: int | None
    actual_max_tokens: int | None
    problems: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.problems


def check_embedding_readiness(model_directory: Path, spec: EmbeddingSpec) -> EmbeddingReadiness:
    """Inspect a local snapshot; never download or load model weights."""
    required_files = (
        "config.json", "tokenizer_config.json", "tokenizer.json",
        "pytorch_model.bin", "sparse_linear.pt",
    )
    packages = {
        name: importlib.util.find_spec(name) is not None
        for name in ("torch", "transformers", "FlagEmbedding")
    }
    problems = [f"missing package: {name}" for name, found in packages.items() if not found]
    files_present = all((model_directory / name).is_file() for name in required_files)
    if not files_present:
        problems.append("model snapshot is missing required files")
    dimension: int | None = None
    max_tokens: int | None = None
    try:
        config = json.loads((model_directory / "config.json").read_text(encoding="utf-8"))
        tokenizer = json.loads(
            (model_directory / "tokenizer_config.json").read_text(encoding="utf-8")
        )
        dimension = int(config["hidden_size"])
        max_tokens = int(tokenizer["model_max_length"])
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        problems.append("model or tokenizer configuration is unreadable")
    else:
        if dimension != spec.dimension:
            problems.append("configured dense dimension differs from model snapshot")
        if max_tokens != spec.model_max_tokens:
            problems.append("configured token limit differs from model snapshot")
    return EmbeddingReadiness(
        model_directory=model_directory,
        model_files_present=files_present,
        installed_packages=packages,
        actual_dimension=dimension,
        actual_max_tokens=max_tokens,
        problems=tuple(problems),
    )
