"""Local BGE reranker adapter with explicit limits and no implicit download."""

from pathlib import Path
from typing import Any


class BGERerankerProvider:
    def __init__(
        self,
        model_directory: Path,
        *,
        model_version: str,
        device: str = "cpu",
        batch_size: int = 8,
        query_max_tokens: int = 256,
        pair_max_tokens: int = 512,
        model: Any | None = None,
    ) -> None:
        if not model_version.strip():
            raise ValueError("model_version must not be empty")
        if batch_size < 1 or query_max_tokens < 1 or pair_max_tokens < query_max_tokens:
            raise ValueError("invalid batch size or token limits")
        self._name = "BAAI/bge-reranker-v2-m3"
        self._version = model_version.strip()
        self._batch_size = batch_size
        self._query_max_tokens = query_max_tokens
        self._pair_max_tokens = pair_max_tokens
        if model is None:
            if not model_directory.is_dir():
                raise FileNotFoundError(
                    f"local reranker model directory does not exist: {model_directory}"
                )
            if device.startswith("cuda"):
                import torch

                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA was requested but project Torch has no available CUDA device")
            from FlagEmbedding import FlagReranker  # type: ignore[import-untyped]

            model = FlagReranker(
                str(model_directory), devices=device, use_fp16=device.startswith("cuda"),
                batch_size=batch_size, query_max_length=query_max_tokens,
                max_length=pair_max_tokens, normalize=True,
            )
        self._model = model

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    def score(self, query: str, passages: tuple[str, ...]) -> tuple[float, ...]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if not passages:
            return ()
        tokenizer = self._model.tokenizer
        query_tokens = tokenizer.encode(query, add_special_tokens=True, truncation=False)
        if len(query_tokens) > self._query_max_tokens:
            raise ValueError("query exceeds configured reranker token limit")
        for passage in passages:
            if not passage.strip():
                raise ValueError("passage must not be empty")
            pair_tokens = tokenizer.encode(
                query, passage, add_special_tokens=True, truncation=False,
            )
            if len(pair_tokens) > self._pair_max_tokens:
                raise ValueError("query-passage pair exceeds configured reranker token limit")
        raw = self._model.compute_score(
            [(query, passage) for passage in passages],
            batch_size=self._batch_size,
            max_length=self._pair_max_tokens,
            normalize=True,
        )
        values = [raw] if isinstance(raw, (int, float)) else raw
        if len(values) != len(passages):
            raise ValueError("reranker returned a different number of scores")
        return tuple(float(value) for value in values)
