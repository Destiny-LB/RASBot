"""Deterministic evidence selection from a persisted evaluation pool."""
import json


class Selection:
    def __init__(self, runtime, agent_id='precision'):
        self.runtime = runtime
        self.agent = runtime.registry.get(agent_id)
        if not self.agent.evolution: raise ValueError("Agent does not support evolution")
        self.path = runtime.store.root / ('evaluation-pool.json' if agent_id == 'precision' else 'evaluation-pool-' + agent_id + '.json')

    def pool(self):
        if not self.path.exists():
            tasks = [s for s in self.agent.catalog() if self.agent.eligible(s)]
            with self.path.open('x', encoding='utf-8') as out:
                json.dump({'version': 1, 'slugs': tasks}, out)
        return json.loads(self.path.read_text(encoding='utf-8'))['slugs']

    def recommend(self, previous_sources=None, previous_slugs=None):
        pool = [s for s in self.pool() if self.agent.eligible(s)]
        choices = []
        for t in self.runtime.store.snapshot()['tasks']:
            result = json.loads(t['result'])
            if t['domain'] == self.agent.id and t['slug'] in pool and t['state'] in ('generated', 'validation_failed', 'engine_failed') and result.get('session_id'):
                choices.append({k: t[k] for k in ('id', 'slug', 'state', 'created')})
        # Stable priority for the initial recommendation; rotate complete valid
        # combinations only when the caller supplies its current selection.
        ordered = [t for t in choices if t['state'] != 'generated'] + [t for t in choices if t['state'] == 'generated']
        combinations = []
        seen = set()
        for primary in ordered:
            sources = [primary]
            opposite = next((t for t in choices if t['slug'] == primary['slug']
                             and (t['state'] == 'generated') != (primary['state'] == 'generated')), None)
            if opposite:
                sources.append(opposite)
            remaining = sorted((s for s in pool if s != primary['slug']),
                               key=lambda s: self.agent.holdout_key(primary['slug'], s))
            for holdout in remaining:
                slugs = [primary['slug'], holdout]
                key = (tuple(sorted(t['id'] for t in sources)), tuple(sorted(slugs)))
                if key not in seen:
                    seen.add(key)
                    combinations.append((sources, slugs, key))
        index = 0
        if previous_sources is not None and previous_slugs is not None:
            previous = (tuple(sorted(previous_sources)), tuple(sorted(previous_slugs)))
            for i, (_, _, key) in enumerate(combinations):
                if key == previous:
                    index = (i + 1) % len(combinations)
                    break
        sources, slugs = combinations[index][:2] if combinations else ([], [])
        ready = bool(sources) and len(slugs) == 2
        return {'agent_id': self.agent.id, 'agent_name': self.agent.name, 'goal': self.agent.evolution_goal,
                'task_titles': {s: self.agent.title(s) for s in pool}, 'source_ids': [t['id'] for t in sources], 'slugs': slugs,
                'source_choices': choices, 'pool': pool, 'ready': ready,
                'reason': ('优先选择最近失败任务，并加入同任务的成功对照（若有）；无失败时使用最近成功任务。另选未参与本轮诊断的任务作保留任务。'
                           if ready else '需要至少一项有执行会话的已结束任务，以及两个具备提示词的评测任务。'),
                'alternative_count': max(0, len(combinations) - 1), 'pool_version': 1, 'policy': 'recent-failure-with-success-control-v1'}
