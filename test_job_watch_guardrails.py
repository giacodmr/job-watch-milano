#!/usr/bin/env python3
import unittest

from harden_job_watch_state import REQUIRED_SEMANTIC_FIELDS, needs_applied_review, semantic_decision_valid


class GuardrailTests(unittest.TestCase):
    def base_decision(self):
        row = {field: None for field in REQUIRED_SEMANTIC_FIELDS}
        row.update({
            "fingerprint": "abc",
            "analysis_status": "ANALYZED",
            "analysis_method": "chatgpt_semantic_title_metadata",
            "fit_score": 80,
            "mandatory_vs_preferred_requirements": {"mandatory": [], "preferred": []},
            "people_management_required": False,
            "individual_contributor_possible": True,
            "decision_scope_and_ownership": "IC scope",
            "role_level_assessment": "EARLY_MID",
            "seniority_evidence": "No mandatory management scope.",
            "final_experience_status": "TARGET_0_5",
            "reportable": True,
            "rationale": "Relevant role.",
            "analyzed_at": "2026-10-03T08:00:00Z",
            "l68_status": "NO",
        })
        return row

    def test_missing_required_field_fails(self):
        decision = self.base_decision()
        decision.pop("salary_source")
        valid, reason = semantic_decision_valid(decision, {"fingerprint": "abc", "title": "Business Analyst", "priority_company": False})
        self.assertFalse(valid)
        self.assertIn("missing_fields", reason)

    def test_senior_requires_full_jd(self):
        decision = self.base_decision()
        valid, reason = semantic_decision_valid(decision, {"fingerprint": "abc", "title": "Senior Business Analyst", "priority_company": False})
        self.assertFalse(valid)
        self.assertEqual(reason, "full_jd_required")

    def test_standard_decision_passes(self):
        decision = self.base_decision()
        valid, reason = semantic_decision_valid(decision, {"fingerprint": "abc", "title": "Business Analyst", "priority_company": False})
        self.assertTrue(valid)
        self.assertIsNone(reason)

    def test_applied_updated_needs_review(self):
        self.assertTrue(needs_applied_review({
            "current_open": True,
            "user_decision": "APPLIED",
            "current_status": "UPDATED",
            "analysis_method": "user_decision_applied",
        }))


if __name__ == "__main__":
    unittest.main()
