import unittest

import job_watch_bridge as bridge


class JobWatchBridgeValidationTests(unittest.TestCase):
    def test_select_requires_small_fetched_packet(self):
        good = {
            "version": "1.0",
            "request_id": "req",
            "action": "select",
            "batch": "jw1",
            "limit": 1,
            "fetch": True,
        }
        bridge.validate_select_request(good)
        with self.assertRaisesRegex(ValueError, "select_limit_invalid"):
            bridge.validate_select_request({**good, "limit": 6})
        with self.assertRaisesRegex(ValueError, "select_requires_fetch"):
            bridge.validate_select_request({**good, "fetch": False})

    def test_apply_requires_bound_patch_and_packet_hash(self):
        good = {
            "version": "1.0",
            "request_id": "apply",
            "action": "apply",
            "batch": "jw1",
            "parent_request_id": "select",
            "packet_sha256": "a" * 64,
            "patch": {
                "batch": "jw1",
                "snapshot": {"job_memory_jw1.json": "hash"},
                "semantic_decisions": {"Company::1": {"fingerprint": "fp"}},
            },
        }
        self.assertIs(bridge.validate_apply_request(good), good["patch"])
        with self.assertRaisesRegex(ValueError, "patch_batch_mismatch"):
            bridge.validate_apply_request({**good, "patch": {**good["patch"], "batch": "jw2"}})
        with self.assertRaisesRegex(ValueError, "packet_sha256_invalid"):
            bridge.validate_apply_request({**good, "packet_sha256": "bad"})

    def test_apply_is_bounded_to_five_decisions(self):
        decisions = {f"Company::{i}": {"fingerprint": str(i)} for i in range(6)}
        request = {
            "version": "1.0",
            "request_id": "apply",
            "action": "apply",
            "batch": "jw1",
            "parent_request_id": "select",
            "packet_sha256": "b" * 64,
            "patch": {
                "batch": "jw1",
                "snapshot": {"job_memory_jw1.json": "hash"},
                "semantic_decisions": decisions,
            },
        }
        with self.assertRaisesRegex(ValueError, "patch_decision_count_invalid"):
            bridge.validate_apply_request(request)


if __name__ == "__main__":
    unittest.main()
