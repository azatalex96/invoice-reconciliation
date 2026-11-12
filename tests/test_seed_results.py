"""The app must reproduce the starter pack's expected-seed-results.json."""
import unittest

from tests.helpers import DATA, SEED_FILE, load_json, run_batch

EXPECTED = load_json(DATA / "seed" / "expected-seed-results.json")


class SeedResultsTest(unittest.TestCase):
    def check(self, state):
        for expected in EXPECTED:
            result = state["invoices"][expected["file_id"]]["result"]
            for key, value in expected.items():
                if key == "file_id":
                    continue
                with self.subTest(file_id=expected["file_id"], key=key):
                    self.assertEqual(result[key], value)

    def test_seed_only_batch(self):
        _, _, state = run_batch([SEED_FILE])
        self.assertEqual(state["order"], [e["file_id"] for e in EXPECTED])
        self.check(state)

    def test_seed_results_unchanged_in_full_batch(self):
        _, _, state = run_batch()
        self.check(state)


if __name__ == "__main__":
    unittest.main()
