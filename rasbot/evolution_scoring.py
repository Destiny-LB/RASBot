"""Paired generation efficiency, distinct from numerical reliability quality."""
import math
from datetime import datetime


def elapsed(task, started):
    """Use platform terminal events, not polling time or agent-reported duration."""
    if not started:
        return None
    terminal = 'state.' + task['state']
    for event in reversed(task['events']):
        if event['kind'] == terminal:
            try:
                seconds = (datetime.fromisoformat(event['created']) - datetime.fromisoformat(started)).total_seconds()
                return seconds if math.isfinite(seconds) and seconds > 0 else None
            except (TypeError, ValueError):
                return None
    return None


def decide(trials, slugs, policy):
    repetitions = policy.get('efficiency_repetitions', 2)
    groups = {}
    for trial in trials:
        key = (trial['slug'], trial.get('replicate', 0))
        role = trial['role']
        pair = groups.setdefault(key, {})
        if role not in ('baseline', 'candidate') or role in pair:
            return {'state': 'inconclusive', 'reason': '配对记录重复或角色无效'}
        pair[role] = trial
    rounds = {r for _, r in groups}
    if rounds not in ({0}, set(range(repetitions))) or set(groups) != {(s, r) for s in slugs for r in rounds}:
        return {'state': 'inconclusive', 'reason': '评测任务或复测记录不完整'}
    if any(set(pair) != {'baseline', 'candidate'} for pair in groups.values()):
        return {'state': 'inconclusive', 'reason': '基线与候选没有完整配对'}
    if any(not t.get('comparable', False) or t.get('manual_intervention') for t in trials):
        return {'state': 'inconclusive', 'reason': '存在不可比较的执行或人工干预'}
    base = sum(t['passed'] for t in trials if t['role'] == 'baseline')
    candidate = sum(t['passed'] for t in trials if t['role'] == 'candidate')
    if candidate != len(groups):
        return {'state': 'rejected', 'reason': '候选未通过全部合规性门槛'}
    if candidate > base and rounds == {0}:
        return {'state': 'promoted', 'basis': 'generation_compliance', 'reason': '候选全部通过，且通过数严格优于基线'}
    if candidate != base:
        return {'state': 'inconclusive', 'reason': '效率复测中合规性发生变化，不能确认效率收益'}
    pairs = []
    for (slug, replicate), pair in sorted(groups.items()):
        b, c = pair['baseline'].get('duration_seconds'), pair['candidate'].get('duration_seconds')
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in (b, c)):
            return {'state': 'rejected', 'reason': '合规性持平，缺少可信的执行耗时，保留基线'}
        pairs.append({'slug': slug, 'replicate': replicate, 'baseline_seconds': b,
                      'candidate_seconds': c, 'ratio': c / b})
    threshold = policy['efficiency_max_ratio']
    evidence = {'pairs': pairs, 'max_ratio': threshold,
                'scope': 'Generation wall time including tools and validation; not numerical reliability or statistical significance'}
    if any(p['ratio'] > threshold for p in pairs):
        return {**evidence, 'state': 'rejected', 'reason': '合规性持平，但并非每个任务每次执行都达到耗时改善门槛'}
    if len(rounds) < repetitions:
        return {**evidence, 'state': 'confirming', 'reason': '初次效率比较达标，交换顺序复测后再决定'}
    return {**evidence, 'state': 'promoted', 'basis': 'generation_efficiency',
            'reason': '合规性全部通过，且每个任务在两次配对执行中均达到耗时改善门槛'}
