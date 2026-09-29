"""Explicit one-off initialization; never create collections in health checks."""

import os

from finsight.core.deployment import require_runtime_environment


def main():
    require_runtime_environment(os.environ)
    from pymilvus import MilvusClient

    from finsight.core.config import get_settings
    from finsight.infrastructure.vector.milvus_hybrid import MilvusHybridVectorStore

    settings = get_settings()
    client = MilvusClient(uri=settings.milvus_uri, timeout=30)
    try:
        MilvusHybridVectorStore(settings.milvus_uri, collection_name=settings.milvus_collection,
                               dimension=settings.embedding_dimension, client=client).ensure_collection()
    finally:
        client.close()
    print("Deployment vector schema initialized or validated; no documents imported")


if __name__ == "__main__":
    main()
