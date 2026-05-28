"""Firestore 実装。

ローカル動作確認は Firestore emulator を使う:

    $ gcloud emulators firestore start --host-port=localhost:8085
    $ export FIRESTORE_EMULATOR_HOST=localhost:8085

google-cloud-firestore はオプション依存 (`pip install '.[firestore]'`)。
本番では Cloud Run の Application Default Credentials で自動認証される。
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from app.storage.base import Storage
from app.storage.models import DigestRecord, Paper
from app.utils.exceptions import FirestoreError


class FirestoreStorage(Storage):
    def __init__(self, project: str | None = None) -> None:
        try:
            from google.cloud import firestore  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise FirestoreError(
                "google-cloud-firestore が未インストールです。"
                "`pip install '.[firestore]'` を実行してください"
            ) from exc
        kwargs: dict = {}
        if project:
            kwargs["project"] = project
        from google.cloud import firestore as _fs

        self._db = _fs.Client(**kwargs)

    def is_already_sent(self, arxiv_id: str) -> bool:
        doc = self._db.collection("sent_papers").document(arxiv_id).get()
        return doc.exists

    def mark_as_sent(self, papers: list[Paper], digest_id: str) -> None:
        batch = self._db.batch()
        now = datetime.now(timezone.utc)
        for p in papers:
            ref = self._db.collection("sent_papers").document(p.arxiv_id)
            batch.set(
                ref,
                {"arxiv_id": p.arxiv_id, "sent_at": now, "digest_id": digest_id},
            )
        batch.commit()

    def save_digest(self, digest: DigestRecord) -> None:
        self._db.collection("digest_history").document(digest.digest_id).set(
            digest.model_dump(mode="json")
        )

    def get_digest(self, digest_id: str) -> DigestRecord | None:
        doc = self._db.collection("digest_history").document(digest_id).get()
        if not doc.exists:
            return None
        return DigestRecord.model_validate(doc.to_dict())

    def list_digests(self, limit: int = 10) -> list[DigestRecord]:
        from google.cloud.firestore_v1 import Query

        query = (
            self._db.collection("digest_history")
            .order_by("executed_at", direction=Query.DESCENDING)
            .limit(limit)
        )
        return [DigestRecord.model_validate(d.to_dict()) for d in query.stream()]

    def get_cost_today(self, today: date | None = None) -> float:
        key = (today or date.today()).isoformat()
        doc = self._db.collection("cost_tracker").document(key).get()
        if not doc.exists:
            return 0.0
        return float(doc.to_dict().get("total_cost_usd", 0.0))

    def add_cost(self, cost_usd: float, today: date | None = None) -> float:
        from google.cloud import firestore as _fs

        key = (today or date.today()).isoformat()
        ref = self._db.collection("cost_tracker").document(key)
        ref.set(
            {
                "date": key,
                "total_cost_usd": _fs.Increment(cost_usd),
                "request_count": _fs.Increment(1),
                "updated_at": datetime.now(timezone.utc),
            },
            merge=True,
        )
        return float(ref.get().to_dict().get("total_cost_usd", 0.0))
