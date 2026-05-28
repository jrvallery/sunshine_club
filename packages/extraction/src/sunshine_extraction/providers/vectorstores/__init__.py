"""Local vector store providers."""

from sunshine_extraction.providers.vectorstores.base import VectorStoreProvider, VectorStoreUpsertResult
from sunshine_extraction.providers.vectorstores.noop import NoopVectorStoreProvider
from sunshine_extraction.providers.vectorstores.qdrant import QdrantVectorStoreProvider
from sunshine_extraction.providers.vectorstores.sqlite_golden import SQLiteGoldenVectorStoreProvider

__all__ = [
    "NoopVectorStoreProvider",
    "QdrantVectorStoreProvider",
    "SQLiteGoldenVectorStoreProvider",
    "VectorStoreProvider",
    "VectorStoreUpsertResult",
]
