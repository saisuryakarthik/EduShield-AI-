"""The deployed model artifact must be identifiable and hash-pinned."""

import os
import sys
import unittest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from ai.models import predict  # noqa: E402


class ModelMetadataTests(unittest.TestCase):
    def test_version_is_exposed_from_config(self):
        self.assertEqual(
            predict.MODEL_VERSION,
            predict.CONFIG.get("model_version"),
        )
        self.assertEqual(
            predict.get_model_info()["model_version"],
            predict.MODEL_VERSION,
        )

    def test_pinned_digest_matches_the_loaded_artifact(self):
        pinned = predict.CONFIG.get("artifact_sha256")

        self.assertTrue(pinned)
        self.assertEqual(
            predict.file_sha256(predict.MODEL_PATH),
            pinned.lower(),
        )

    def test_changed_artifact_is_refused(self):
        with self.assertRaisesRegex(ValueError, "integrity check failed"):
            predict.verify_artifact_integrity(
                predict.MODEL_PATH,
                "0" * 64,
            )

    def test_missing_pin_is_tolerated_for_older_artifacts(self):
        self.assertTrue(
            predict.verify_artifact_integrity(predict.MODEL_PATH, None)
        )


if __name__ == "__main__":
    unittest.main()
