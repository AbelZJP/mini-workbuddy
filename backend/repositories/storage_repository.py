from __future__ import annotations

from ..storage import Store


class StorageRepository(Store):
    """为现有本地 Store 提供稳定的业务层持久化边界。"""
