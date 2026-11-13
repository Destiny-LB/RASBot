"""Only engine idle timestamps establish completion, never model text."""
from datetime import datetime, timezone
import math


def completion(task, started, budget):
    if task['state'] in ('engine_running', 'engine_starting', 'engine_unknown', 'waiting_permission'):
        return 'running'
    value = task['result'].get('engine_completed_ms')
    if type(value) not in (int, float) or not math.isfinite(value):
        return 'unknown'
    seconds = value / 1000
    if seconds < started.timestamp() or seconds > datetime.now(timezone.utc).timestamp():
        return 'unknown'
    return 'within_budget' if seconds - started.timestamp() <= budget else 'over_budget'
