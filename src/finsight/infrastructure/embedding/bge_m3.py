"""Local BGE-M3 adapter with explicit token and shape checks."""

from pathlib import Path
from typing import Any

from finsight.domain.embedding import EmbeddingInput, EmbeddingOutput, EmbeddingSpec, QueryEmbedding


class BGEM3EmbeddingProvider:
    def __init__(
        self,
        model_directory: Path,
        *,
        spec: EmbeddingSpec | None = None,
        device: str = "cpu",
        batch_size: int = 1,
        model: Any | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.spec = spec or EmbeddingSpec()
        self.batch_size = batch_size
        if model is None:
            if device.startswith("cuda"):
                import torch

                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA was requested but project Torch has no available CUDA device")
            from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-untyped]

            model = BGEM3FlagModel(
                str(model_directory),
                devices=device,
                use_fp16=device.startswith("cuda"),
                batch_size=batch_size,
                query_max_length=self.spec.query_max_tokens,
                passage_max_length=self.spec.batch_max_tokens,
                return_dense=True,
                return_sparse=True,
                return_colbert_vecs=False,
            )
        self._model = model

    def count_tokens(self, text: str) -> int:
        if not text.strip():
            raise ValueError("text must not be empty")
        # Include special tokens and disable truncation so a long table cannot disappear silently.
        return len(self._model.tokenizer.encode(text, add_special_tokens=True, truncation=False))

    def encode_documents(self, inputs: tuple[EmbeddingInput, ...]) -> tuple[EmbeddingOutput, ...]:
        if not inputs:
            return ()
        if len({item.chunk_id for item in inputs}) != len(inputs):
            raise ValueError("chunk IDs must be unique within a batch")
        counts = [self.count_tokens(item.text) for item in inputs]
        for count in counts:
            self.spec.validate_tokens(count)
        raw = self._model.encode_corpus(
            [item.text for item in inputs],
            batch_size=self.batch_size,
            max_length=self.spec.batch_max_tokens,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense_rows, sparse_rows = self._rows(raw, len(inputs))
        outputs = tuple(
            EmbeddingOutput(
                chunk_id=item.chunk_id,
                model_name=self.spec.model_name,
                token_count=count,
                dense=tuple(float(value) for value in dense),
                sparse={int(key): float(value) for key, value in sparse.items()},
            )
            for item, count, dense, sparse in zip(
                inputs, counts, dense_rows, sparse_rows, strict=True
            )
        )
        for output in outputs:
            output.validate(self.spec)
        return outputs

    def encode_query(self, query: str) -> QueryEmbedding:
        token_count = self.count_tokens(query)
        if token_count > self.spec.query_max_tokens:
            raise ValueError("query exceeds configured token limit")
        raw = self._model.encode_queries(
            [query],
            batch_size=1,
            max_length=self.spec.query_max_tokens,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        dense_rows, sparse_rows = self._rows(raw, 1)
        output = QueryEmbedding(
            model_name=self.spec.model_name,
            token_count=token_count,
            dense=tuple(float(value) for value in dense_rows[0]),
            sparse={int(key): float(value) for key, value in sparse_rows[0].items()},
        )
        output.validate(self.spec)
        return output

    @staticmethod
    def _rows(raw: dict[str, Any], expected_count: int) -> tuple[Any, Any]:
        dense = raw.get("dense_vecs")
        sparse = raw.get("lexical_weights")
        if dense is None or sparse is None or len(dense) != expected_count or len(sparse) != expected_count:
            raise ValueError("model returned incomplete or misaligned dense/sparse output")
        return dense, sparse
