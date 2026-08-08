"""Storage Adapter 层：pipeline 不感知底层存储（file / supabase）"""
from collector.context_store.adapters.base import StorageAdapter, get_adapter
from collector.context_store.adapters.file_adapter import FileStorageAdapter
from collector.context_store.adapters.supabase_adapter import SupabaseStorageAdapter

__all__ = [
    "StorageAdapter",
    "get_adapter",
    "FileStorageAdapter",
    "SupabaseStorageAdapter",
]
