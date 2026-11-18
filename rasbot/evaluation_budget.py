"""Confirmation allocations derived from observed paired wall time within a fixed cap."""
from .evaluation_policy import QUALITY_POLICY
import math

def confirmation_plan(run):
    policy=run['policy'];cap=policy['trial_seconds']
    values=[t.get('duration_seconds') for t in run['trials'] if t.get('replicate',0)==0]
    known=len(values)==2*len(run['slugs']) and all(type(v)in (int,float) and math.isfinite(v) and v>0 for v in values)
    adaptive=policy.get('scoring_version')==QUALITY_POLICY and known
    seconds=min(cap,max(300,math.ceil(max(values)*1.5+120))) if adaptive else cap
    overhead=policy.get('overhead_seconds',0)
    return dict(version='observed-confirmation-budget-v1',trial_seconds=seconds,
                required_seconds=2*len(run['slugs'])*seconds+overhead,
                observed=known,adaptive=adaptive,multiplier=1.5,margin_seconds=120,
                scope='Same cap for both arms; no automatic extension beyond authorized deadline')


class BudgetExhausted(TimeoutError):
    pass


def remaining(deadline, cap):
    """One monotonic deadline shared by sequential local acceptance steps."""
    import time
    value=cap if deadline is None else min(cap,deadline-time.monotonic())
    if value<=0:raise BudgetExhausted('budget_exhausted')
    return value
