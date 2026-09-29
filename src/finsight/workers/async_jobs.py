"""Run the Redis dispatcher, document worker, or both as a separate process."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from socket import gethostname
from time import sleep

from redis import Redis

from finsight.core.config import get_settings
from finsight.infrastructure.database.session import SessionFactory
from finsight.infrastructure.embedding.bge_m3 import BGEM3EmbeddingProvider
from finsight.infrastructure.parsers.mineru import MinerUDocumentParser
from finsight.infrastructure.parsers.mineru_normalizer import normalize_mineru_output
from finsight.infrastructure.queue.redis_stream import RedisStreamQueue
from finsight.infrastructure.storage.local import LocalObjectStorage
from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore
from finsight.services.async_job_dispatcher import AsyncJobDispatcher
from finsight.services.async_job_worker import AsyncJobWorker, DocumentTaskHandler
from finsight.services.document_chunk_indexing import DocumentChunkIndexingService
from finsight.services.document_parser import ParserOutput
from finsight.services.document_parsing import DocumentParsingService
from finsight.services.worker_heartbeat import pulse


def _normalize(output: ParserOutput, document_id: int):
    return normalize_mineru_output(output, document_id=document_id)


def _handler(model_path: str | None, device: str) -> DocumentTaskHandler:
    if not model_path or not Path(model_path).is_dir():
        raise ValueError("worker requires an existing --model-path for document indexing")
    settings = get_settings()
    parsing = DocumentParsingService(
        SessionFactory,
        LocalObjectStorage(settings.object_storage_root),
        MinerUDocumentParser(settings.mineru_api_url, max_wait_seconds=600),
        _normalize,
    )
    indexing = DocumentChunkIndexingService(
        SessionFactory,
        BGEM3EmbeddingProvider(Path(model_path), device=device, batch_size=2),
        MilvusHybridVectorStore(
            settings.milvus_uri,
            collection_name=settings.milvus_collection,
            dimension=settings.embedding_dimension,
        ),
    )
    return DocumentTaskHandler(parsing, indexing)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run project async jobs outside the API process")
    parser.add_argument("--role", choices=("dispatcher", "worker", "both"), default="both")
    parser.add_argument("--model-path", default=os.environ.get("FINSIGHT_BGE_MODEL_PATH"))
    parser.add_argument("--device", default=os.environ.get("FINSIGHT_BGE_DEVICE", "cpu"))
    parser.add_argument("--consumer", default=f"{gethostname()}-{os.getpid()}")
    args = parser.parse_args()

    client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    queue = RedisStreamQueue(client)
    queue.ensure_group()
    dispatcher = AsyncJobDispatcher(SessionFactory, queue)
    worker = (
        AsyncJobWorker(SessionFactory, queue, _handler(args.model_path, args.device))
        if args.role in {"worker", "both"}
        else None
    )
    try:
        if get_settings().app_env == "deploy":
            pulse(client, gethostname(), args.role)
        while True:
            if args.role in {"dispatcher", "both"}:
                dispatcher.dispatch_pending()
            if worker is not None:
                worker.process_one(args.consumer, block_ms=1000)
            else:
                sleep(1)
            if get_settings().app_env == "deploy":
                pulse(client, gethostname(), args.role)
    except KeyboardInterrupt:
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
