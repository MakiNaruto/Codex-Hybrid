"""Aggregate retained gateway metadata only; never expose raw request records."""
import json
import time
from datetime import date, timedelta

from management.diagnostics import STATUSES


FIELDS = ('requests', 'requests_with_usage', 'input_tokens', 'output_tokens', 'cached_tokens', 'total_tokens')
REQUEST_STATUSES = STATUSES - {'forwarding_exited', 'forwarding_start_failed'} | {'completed'}
PERIODS = frozenset({'today', 'yesterday', '1', '7', '30'})


def counts():
    return dict.fromkeys(FIELDS, 0)


def token_count(value):
    return value if type(value) is int and 0 <= value <= 10**12 else None


def local_midnight(day):
    return int(time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1)))


def period_bounds(now, period):
    if period in ('today', 'yesterday'):
        local_now = time.localtime(now)
        local_start = date(local_now.tm_year, local_now.tm_mon, local_now.tm_mday)
        if period == 'yesterday':
            local_start -= timedelta(days=1)
        start = local_midnight(local_start)
        end = local_midnight(local_start + timedelta(days=1))
        return start, end, start, end, 3600
    days = int(period)
    cutoff = now - days * 86400
    start = int(cutoff // 86400) * 86400
    return cutoff, now, start, int(now // 86400) * 86400 + 86400, 86400


def report(directory, days=7, now=None, labels=None):
    period = 'today' if days in (1, '1') else str(days)
    if period not in PERIODS:
        raise ValueError('Unsupported usage period')
    labels = labels if isinstance(labels, dict) else {}
    now = time.time() if now is None else now
    cutoff, window_end, start, bucket_end, step = period_bounds(now, period)
    buckets = list(range(start, bucket_end, step))
    calendar_period = period in ('today', 'yesterday')
    period_days = 1 if period in ('today', 'yesterday') else int(period)
    models = {}
    found = failed = False
    for suffix in ('.3', '.2', '.1', ''):
        try:
            with (directory / ('service.jsonl' + suffix)).open('rb') as stream:
                found = True
                while True:
                    line = stream.readline(65536)
                    if not line:
                        break
                    if len(line) == 65536 and not line.endswith(b'\n'):
                        while line and not line.endswith(b'\n'):
                            line = stream.readline(65536)
                        continue
                    try:
                        entry = json.loads(line)
                    except (ValueError, UnicodeError, RecursionError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    timestamp, model, status = entry.get('time'), entry.get('model'), entry.get('status')
                    try:
                        in_range = (cutoff <= timestamp < window_end if calendar_period
                                    else cutoff <= timestamp <= window_end)
                    except TypeError:
                        in_range = False
                    if (type(timestamp) not in (int, float) or timestamp > now or not in_range or not isinstance(model, str)
                            or not 0 < len(model) <= 256 or not isinstance(status, str)
                            or status not in REQUEST_STATUSES):
                        continue
                    if model not in models:
                        row = {'model': model, **counts(),
                               'series': [dict(time=b, **counts()) for b in buckets]}
                        label = labels.get(model)
                        if label:
                            row['provider_name'], row['model_name'] = label
                        models[model] = row
                    row = models[model]
                    bucket = row['series'][int((timestamp - start) // step)]
                    values = counts()
                    values['requests'] = 1
                    usage = entry.get('usage')
                    if isinstance(usage, dict):
                        incoming = token_count(usage.get('input_tokens'))
                        outgoing = token_count(usage.get('output_tokens'))
                        total = token_count(usage.get('total_tokens'))
                        if incoming is not None and outgoing is not None:
                            total = incoming + outgoing
                        if total is not None:
                            values.update(requests_with_usage=1, input_tokens=incoming or 0,
                                          output_tokens=outgoing or 0, total_tokens=total,
                                          cached_tokens=min(token_count(usage.get('cached_tokens')) or 0,
                                                            incoming or 0))
                    for field in FIELDS:
                        row[field] += values[field]
                        bucket[field] += values[field]
        except FileNotFoundError:
            continue
        except OSError:
            failed = True
    period_value = period if calendar_period else int(period)
    return {'generated_at': now, 'period': period_value, 'period_days': period_days,
            'period_start': start, 'period_end': window_end, 'bucket_seconds': step,
            'buckets': buckets, 'models': sorted(models.values(), key=lambda m: (-m['total_tokens'], m['model'])),
            'state': 'partial' if failed and found else 'unavailable' if failed else 'available' if found else 'missing',
            'coverage': {'retained_files_only': True, 'rotation_may_remove_history': True,
                         'read_failed': failed}}
