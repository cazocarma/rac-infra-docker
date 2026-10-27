"""Expiry-aware operator token caching for provisioning and isolated tests.
The issuer owns the token lifetime. This cache never extends it or retries
permission failures; only an explicit acquisition callback can obtain a token.
"""
import math
import time


class TokenLease:
    def __init__(self, acquire, *, clock=time.monotonic):
        self._acquire = acquire
        self._clock = clock
        self._token = None
        self._valid_until = 0
        self.acquisitions = 0
        self.lifetime = None

    def get(self):
        if self._token is not None and self._clock() < self._valid_until:
            return self._token
        self._token = None
        self._valid_until = 0
        started = self._clock()
        result = self._acquire()
        if not isinstance(result, dict):
            raise RuntimeError('Invalid operator token response')
        token, lifetime = result.get('access_token'), result.get('expires_in')
        if (not isinstance(token, str) or not token or
                isinstance(lifetime, bool) or not isinstance(lifetime, (int, float)) or
                not math.isfinite(lifetime) or lifetime <= 0):
            raise RuntimeError('Invalid operator token response')
        until = started + lifetime - min(5, lifetime / 2)
        if self._clock() >= until:
            raise RuntimeError('Operator token acquisition exceeded its usable lifetime')
        self._token, self._valid_until = token, until
        self.acquisitions += 1
        self.lifetime = lifetime
        return token
