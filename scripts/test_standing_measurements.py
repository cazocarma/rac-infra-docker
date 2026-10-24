import unittest
from standing_measurements import distribution, measure_revocation


class MeasurementIntegrity(unittest.TestCase):
    def test_nearest_rank_does_not_interpolate_away_tail(self):
        result = distribution([float(n) for n in range(1, 101)])
        self.assertEqual(result, {'samples': 100, 'p50': 50, 'p95': 95, 'p99': 99, 'max': 100})
        for invalid in ([], [-1], [float('nan')], [float('inf')]):
            with self.assertRaises(ValueError):
                distribution(invalid)

    def test_tiny_or_empty_run_cannot_be_claimed_as_gate_evidence(self):
        for count in (0, 1, 99, 1001, '100'):
            with self.assertRaises(ValueError):
                measure_revocation(None, None, count)


if __name__ == '__main__':
    unittest.main()
