from __future__ import annotations

import unittest

from runtime_sandbox_test_policy import normalize_sandbox_test_results


class RuntimeSandboxTestPolicyTests(unittest.TestCase):
    def test_reachable_dconf_becomes_failure(self):
        result = normalize_sandbox_test_results([
            ("PASS", "dconf D-Bus", "rc=0"),
        ])
        self.assertEqual(result[0][0], "FAIL")
        self.assertIn("raggiungibile", result[0][2])
        self.assertIn("GSETTINGS_BACKEND=keyfile", result[0][2])

    def test_blocked_dconf_becomes_pass(self):
        result = normalize_sandbox_test_results([
            ("FAIL", "dconf D-Bus", "rc=1"),
        ])
        self.assertEqual(result[0][0], "PASS")
        self.assertIn("bloccato", result[0][2])
        self.assertIn("GSETTINGS_BACKEND=keyfile", result[0][2])

    def test_missing_probe_warning_is_not_promoted(self):
        result = normalize_sandbox_test_results([
            ("WARN", "dconf D-Bus", "strumento di test non disponibile"),
        ])
        self.assertEqual(result, [("WARN", "dconf D-Bus", "strumento di test non disponibile")])

    def test_missing_result_failure_is_not_promoted(self):
        result = normalize_sandbox_test_results([
            ("FAIL", "dconf D-Bus", "risultato assente"),
        ])
        self.assertEqual(result, [("FAIL", "dconf D-Bus", "risultato assente")])

    def test_malformed_or_missing_tool_rc_is_not_promoted(self):
        for detail in ("rc=not-an-int", "rc=127", "rc=0"):
            with self.subTest(detail=detail):
                result = normalize_sandbox_test_results([
                    ("FAIL", "dconf D-Bus", detail),
                ])
                self.assertEqual(result, [("FAIL", "dconf D-Bus", detail)])

    def test_unrelated_results_are_unchanged(self):
        original = [
            ("PASS", "rete persistente", "[network] assente"),
            ("FAIL", "whitelist profilo", "unsafe"),
        ]
        self.assertEqual(normalize_sandbox_test_results(original), original)

    def test_duplicate_dconf_result_is_rejected(self):
        with self.assertRaises(RuntimeError):
            normalize_sandbox_test_results([
                ("FAIL", "dconf D-Bus", "rc=1"),
                ("FAIL", "dconf D-Bus", "rc=1"),
            ])


if __name__ == "__main__":
    unittest.main()
