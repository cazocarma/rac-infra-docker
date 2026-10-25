"""Bounded real-request measurements; no credentials or account IDs in reports."""
from concurrent.futures import ThreadPoolExecutor
import math
import re
import threading
import time


def distribution(values):
    ordered = sorted(values)
    if not ordered or any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError('Nonempty finite nonnegative samples required')
    def rank(percent):
        return ordered[math.ceil(len(ordered) * percent) - 1]
    return {'samples': len(ordered), 'p50': rank(.50), 'p95': rank(.95),
            'p99': rank(.99), 'max': ordered[-1]}


def measure_revocation(call, transition, samples=100):
    """call(group, instance) returns status and monotonic request boundaries.

    transition(status) returns a bracket around the actual database COMMIT.
    The earlier bracket edge makes the response-based bound conservative.
    No 5xx/timeout/missing worker is discarded to improve a percentile.
    """
    if not isinstance(samples, int) or not 100 <= samples <= 1000:
        raise ValueError('Revocation gate requires 100..1000 distinct transitions')
    groups = ('user.profile', 'match.availability', 'chat.send')
    keys = [(group, instance) for group in groups for instance in (1, 2)]
    period = .1
    records = {key: {'first_denial_bound_ms': [], 'last_success_bound_ms': [],
                     'restoration_bound_ms': [], 'restoration_denials': 0,
                     'http_ms': [], 'allowed': 0, 'denied': 0, 'rate_overruns': 0} for key in keys}
    commit_uncertainty_ms = []
    begun = time.monotonic_ns()
    for _ in range(samples):
        active_started, _ = transition('active')
        barrier = threading.Barrier(len(keys) + 1)
        stop = threading.Event()
        seen = {key: threading.Event() for key in keys}
        first_denial, successes = {}, {key: [] for key in keys}

        def worker(key):
            record = records[key]
            denied = False
            try:
                # A positive request immediately before this trial rules out
                # invalid input, ownership, stale login or a dead route.
                restore_deadline = time.monotonic() + 5
                while True:
                    warm = call(*key)
                    if warm['status'] in (200, 201):
                        record['restoration_bound_ms'].append(max(0, (warm['finished_ns'] - active_started) / 1e6))
                        break
                    if warm['status'] != 403 or time.monotonic() >= restore_deadline:
                        raise AssertionError('Positive revocation control failed: ' + key[0])
                    record['restoration_denials'] += 1
                    # An invalidated provisional lease can require a retry after
                    # reversal. Record that separately instead of hiding it in
                    # the revocation or HTTP percentile samples.
                    time.sleep(.01)
                barrier.wait(timeout=10)
                while not stop.is_set():
                    target = time.monotonic() + period
                    result = call(*key)
                    status = result['status']
                    record['http_ms'].append((result['finished_ns'] - result['started_ns']) / 1e6)
                    if status in (200, 201):
                        if denied:
                            raise AssertionError('Permission returned after a denial without reversal')
                        successes[key].append(result['finished_ns'])
                        record['allowed'] += 1
                    elif status == 403:
                        record['denied'] += 1
                        if not denied:
                            first_denial[key] = result['finished_ns']
                            denied = True
                            seen[key].set()
                    else:
                        raise AssertionError('Unexpected HTTP status in revocation load')
                    delay = target - time.monotonic()
                    if delay < 0:
                        record['rate_overruns'] += 1
                    stop.wait(max(0, delay))
            except BaseException:
                barrier.abort()
                seen[key].set()
                raise

        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            futures = [pool.submit(worker, key) for key in keys]
            try:
                barrier.wait(timeout=10)
                earliest, latest = transition('suspended')
                if latest < earliest:
                    raise AssertionError('Invalid commit bracket')
                commit_uncertainty_ms.append((latest - earliest) / 1e6)
                deadline = time.monotonic() + 5
                for key in keys:
                    if not seen[key].wait(max(0, deadline - time.monotonic())):
                        raise AssertionError('No denial within revocation budget: ' + key[0])
                # Continue after each first denial: a later permissive response
                # without a reversal is a failure, not a smaller sample set.
                time.sleep(.15)
            finally:
                stop.set()
                barrier.abort()
            for future in futures:
                future.result(timeout=10)
        for key in keys:
            if key not in first_denial:
                raise AssertionError('Worker produced no measurable denial')
            first = (first_denial[key] - earliest) / 1e6
            last = max([0] + [(end - earliest) / 1e6 for end in successes[key] if end >= earliest])
            if first < 0 or first > 5000 or last > 5000:
                raise AssertionError('Revocation budget exceeded')
            records[key]['first_denial_bound_ms'].append(first)
            records[key]['last_success_bound_ms'].append(last)
    transition('active')
    return {'schema_version': 1, 'kind': 'compose_revocation', 'transitions': samples,
            'instances_per_service': 2, 'concurrency': len(keys),
            'target_requests_per_second_per_worker': 1 / period,
            'duration_seconds': (time.monotonic_ns() - begun) / 1e9,
            'commit_bracket_ms': distribution(commit_uncertainty_ms),
            'groups': [{'operation': key[0], 'instance': key[1],
                        **{name: distribution(value) if isinstance(value, list) else value
                           for name, value in record.items()}}
                       for key, record in records.items()]}


def parse_acquire_histogram(text):
    """Read only fixed SDK metric series; no inferred or interpolated p99."""
    expected = {
        'count': r'^rac_standing_acquire_duration_seconds_count\{cache="hit"\} ([0-9]+)$',
        'within_2ms': r'^rac_standing_acquire_duration_seconds_bucket\{cache="hit",le="0\.002"\} ([0-9]+)$',
        'infinity': r'^rac_standing_acquire_duration_seconds_bucket\{cache="hit",le="\+Inf"\} ([0-9]+)$',
    }
    values = {}
    for name, pattern in expected.items():
        matches = re.findall(pattern, text, re.MULTILINE)
        if len(matches) != 1:
            raise AssertionError('Missing or duplicate acquisition metric: ' + name)
        values[name] = int(matches[0])
    if values['count'] != values['infinity'] or values['within_2ms'] > values['count']:
        raise AssertionError('Inconsistent histogram snapshot')
    return values


def measure_hot_acquisition(call, scrape, requests_per_worker=200):
    if not isinstance(requests_per_worker, int) or requests_per_worker < 200:
        raise ValueError('Hot path gate requires at least 200 requests per worker')
    keys = [(group, instance) for group in ('user.profile', 'match.availability', 'chat.send') for instance in (1, 2)]
    before = {key: parse_acquire_histogram(scrape(*key)) for key in keys}
    begun = time.monotonic_ns()

    def worker(key):
        # Confirm eligibility after the last reversal, before measuring traffic.
        deadline = time.monotonic() + 5
        while call(*key)['status'] == 403:
            if time.monotonic() >= deadline:
                raise AssertionError('Warm-path positive control never became allowed')
            time.sleep(.01)
        latencies = []
        for _ in range(requests_per_worker):
            result = call(*key)
            if result['status'] not in (200, 201):
                raise AssertionError('Hot-path traffic unexpectedly denied or failed')
            latencies.append((result['finished_ns'] - result['started_ns']) / 1e6)
        return key, latencies

    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        measured = list(pool.map(worker, keys))
    groups = []
    for key, latencies in measured:
        after = parse_acquire_histogram(scrape(*key))
        total = after['count'] - before[key]['count']
        fast = after['within_2ms'] - before[key]['within_2ms']
        if total < 100 or fast < 0 or fast > total:
            raise AssertionError('Insufficient or reset hot acquisition samples')
        groups.append({'operation': key[0], 'instance': key[1], 'hot_acquisitions': total,
                       'within_2ms': fast, 'fraction_within_2ms': fast / total,
                       'http_ms': distribution(latencies)})
    # Retain slow results. The caller must fail its gate after preserving the
    # report, not throw away evidence because performance was below target.
    return {'concurrency': len(keys), 'requests_per_worker': requests_per_worker,
            'duration_seconds': (time.monotonic_ns() - begun) / 1e9, 'groups': groups,
            'gate_passed': all(group['within_2ms'] >= math.ceil(.99 * group['hot_acquisitions']) for group in groups)}
