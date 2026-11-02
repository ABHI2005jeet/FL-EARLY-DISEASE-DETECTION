from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from local_cloud.iam import AccessDenied
from local_cloud.object_store import LocalObjectStore


class LocalCloudTests(unittest.TestCase):
    def test_sse_s3_metadata_and_audit_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "s3"
            audit_log = Path(tmp) / "events.jsonl"
            store = LocalObjectStore(root=root, audit_log_path=audit_log)
            key = "clients/hospital_1/round_001/weights.json"

            store.put_json(actor="hospital_1", key=key, payload={"ok": True})

            envelope = store.get_envelope(actor="aggregator", key=key)
            self.assertEqual(envelope["metadata"]["server_side_encryption"], "AES256")
            self.assertIsNone(envelope["metadata"]["kms_key_id"])
            self.assertIn('"action": "PutObject"', audit_log.read_text(encoding="utf-8"))

    def test_client_cannot_write_to_another_client_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalObjectStore(
                root=Path(tmp) / "s3",
                audit_log_path=Path(tmp) / "events.jsonl",
            )

            with self.assertRaises(AccessDenied):
                store.put_json(
                    actor="hospital_1",
                    key="clients/hospital_2/round_001/weights.json",
                    payload={"blocked": True},
                )

    def test_client_can_read_global_but_not_peer_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalObjectStore(
                root=Path(tmp) / "s3",
                audit_log_path=Path(tmp) / "events.jsonl",
            )
            store.put_json(
                actor="system",
                key="global/current_model.json",
                payload={"model": "global"},
            )
            store.put_json(
                actor="hospital_2",
                key="clients/hospital_2/round_001/weights.json",
                payload={"model": "peer"},
            )

            self.assertEqual(
                store.get_json(actor="hospital_1", key="global/current_model.json"),
                {"model": "global"},
            )
            with self.assertRaises(AccessDenied):
                store.get_json(
                    actor="hospital_1",
                    key="clients/hospital_2/round_001/weights.json",
                )


if __name__ == "__main__":
    unittest.main()
