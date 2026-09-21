from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from aggregator.trigger import handle_round_timeout, handle_weight_upload_event
from api.local_server import RequestValidationError, validate_patient_payload
from clients.local_client import WeightUploadEvent
from fl_core.dataset import FEATURE_COLUMNS
from local_cloud.metadata_store import LocalMetadataStore


class TriggerAndAPITests(unittest.TestCase):
    def test_upload_trigger_reaches_expected_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata = LocalMetadataStore(Path(tmp) / "rounds.json")
            clients = ["hospital_1", "hospital_2"]
            metadata.initialize_training(
                total_rounds=1,
                expected_clients=clients,
                current_model_key="global/current_model.json",
            )
            metadata.begin_round(
                round_number=1,
                expected_clients=clients,
                timeout_seconds=300,
            )

            first_ready = handle_weight_upload_event(
                event=self._event("hospital_1"),
                metadata=metadata,
                expected_clients=clients,
            )
            second_ready = handle_weight_upload_event(
                event=self._event("hospital_2"),
                metadata=metadata,
                expected_clients=clients,
            )

            self.assertFalse(first_ready)
            self.assertTrue(second_ready)
            self.assertEqual(metadata.get_round(1)["uploads_received"], 2)

    def test_timeout_marks_missing_client_as_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata = LocalMetadataStore(Path(tmp) / "rounds.json")
            clients = ["hospital_1", "hospital_2"]
            metadata.initialize_training(
                total_rounds=1,
                expected_clients=clients,
                current_model_key="global/current_model.json",
            )
            metadata.begin_round(
                round_number=1,
                expected_clients=clients,
                timeout_seconds=300,
            )
            handle_weight_upload_event(
                event=self._event("hospital_1"),
                metadata=metadata,
                expected_clients=clients,
            )

            can_continue = handle_round_timeout(
                round_number=1,
                metadata=metadata,
                expected_clients=clients,
            )

            self.assertTrue(can_continue)
            self.assertEqual(metadata.get_round(1)["skipped_clients"], ["hospital_2"])

    def test_prediction_payload_validation(self) -> None:
        payload = {"features": {column: "1" for column in FEATURE_COLUMNS}}

        parsed = validate_patient_payload(payload)

        self.assertEqual(set(parsed), set(FEATURE_COLUMNS))
        self.assertEqual(parsed["age"], 1.0)

    def test_prediction_payload_rejects_missing_fields(self) -> None:
        with self.assertRaises(RequestValidationError):
            validate_patient_payload({"features": {"age": 54}})

    def _event(self, client_id: str) -> WeightUploadEvent:
        return WeightUploadEvent(
            round_number=1,
            client_id=client_id,
            model_key=f"clients/{client_id}/round_001/weights.json",
            local_accuracy=0.75,
            train_size=10,
            test_size=2,
        )


if __name__ == "__main__":
    unittest.main()
