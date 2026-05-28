"""ストレージ実装を環境に応じて切り替えるファクトリ。"""

from __future__ import annotations

import os

from app.storage.base import Storage
from app.storage.memory import InMemoryStorage


def create_storage(
    *,
    use_firestore: bool | None = None,
    project: str | None = None,
) -> Storage:
    """`use_firestore` 未指定時は `GOOGLE_CLOUD_PROJECT` or `FIRESTORE_EMULATOR_HOST`
    の有無で自動判定する。
    """
    if use_firestore is None:
        use_firestore = bool(os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("FIRESTORE_EMULATOR_HOST"))
    if use_firestore:
        from app.storage.firestore import FirestoreStorage

        return FirestoreStorage(project=project or os.getenv("GOOGLE_CLOUD_PROJECT"))
    return InMemoryStorage()
