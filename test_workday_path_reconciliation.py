#!/usr/bin/env python3
import unittest

from reconcile_workday_target_paths import safe_path_location


class WorkdayPathLocationTests(unittest.TestCase):
    def test_milan_exact(self):
        self.assertEqual(safe_path_location("/job/Milan/Business-Operations-Analyst_R27644"), "Milan")

    def test_milan_italy(self):
        self.assertEqual(safe_path_location("/job/Milan-Italy/Role_R1"), "Milan Italy")

    def test_london_england(self):
        self.assertEqual(safe_path_location("/job/London-England-Angel-Lane/Role_R1"), "London England Angel Lane")

    def test_reject_london_kentucky(self):
        self.assertIsNone(safe_path_location("/job/London-KY/Role_R1"))

    def test_reject_generic_country(self):
        self.assertIsNone(safe_path_location("/job/Italy/Role_R1"))


if __name__ == "__main__":
    unittest.main()
