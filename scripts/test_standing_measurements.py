import unittest
from standing_measurements import distribution, measure_revocation, parse_acquire_histogram


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

    def test_metrics_must_be_complete_and_consistent(self):
        text = '''rac_standing_acquire_duration_seconds_count{cache="hit"} 100
rac_standing_acquire_duration_seconds_bucket{cache="hit",le="0.002"} 99
rac_standing_acquire_duration_seconds_bucket{cache="hit",le="+Inf"} 100
'''
        self.assertEqual(parse_acquire_histogram(text), {'count': 100, 'within_2ms': 99, 'infinity': 100})
        for bad in ('', text + text, text.replace('0.002', '0.005'),
                    text.replace('0.002"} 99', '0.002"} 101'),
                    text.replace('+Inf"} 100', '+Inf"} 98')):
            with self.assertRaises(AssertionError):
                parse_acquire_histogram(bad)


if __name__ == '__main__':
    unittest.main()
