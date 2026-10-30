import unittest
from oauth_token import TokenLease


class TestTokenLease(unittest.TestCase):
    def test_refreshes_from_advertised_lifetime_without_extending_it(self):
        now = [0.0]
        calls = []
        def acquire():
            calls.append(1)
            return {'access_token': 'synthetic-' + str(len(calls)), 'expires_in': 60}
        session = TokenLease(acquire, clock=lambda: now[0])
        self.assertEqual(session.get(), 'synthetic-1')
        now[0] = 54.9
        self.assertEqual(session.get(), 'synthetic-1')
        now[0] = 55
        self.assertEqual(session.get(), 'synthetic-2')
        self.assertEqual(session.lifetime, 60)
        self.assertEqual(session.acquisitions, 2)

    def test_latency_consumes_token_lifetime(self):
        now = [0.0]
        def acquire():
            now[0] += 56
            return {'access_token': 'synthetic', 'expires_in': 60}
        session = TokenLease(acquire, clock=lambda: now[0])
        with self.assertRaisesRegex(RuntimeError, 'usable lifetime'):
            session.get()

    def test_failure_never_returns_expired_cached_token(self):
        now = [0.0]
        def acquire():
            if now[0] > 0:
                raise RuntimeError('fixture unauthorized')
            return {'access_token': 'synthetic', 'expires_in': 60}
        session = TokenLease(acquire, clock=lambda: now[0])
        session.get()
        now[0] = 61
        with self.assertRaisesRegex(RuntimeError, 'fixture unauthorized'):
            session.get()
        self.assertEqual(session.acquisitions, 1)

    def test_rejects_malformed_lifetime_with_opaque_error(self):
        for lifetime in (None, 0, -1, True, '60', float('inf'), float('nan')):
            with self.subTest(lifetime=lifetime):
                session = TokenLease(lambda: {'access_token': 'synthetic', 'expires_in': lifetime})
                with self.assertRaisesRegex(RuntimeError, '^Invalid operator token response$'):
                    session.get()


if __name__ == '__main__':
    unittest.main()
