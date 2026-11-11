import json
import os
from pathlib import Path


DEFAULT_INSTRUCTIONS = ('You plan AI reliability experiments. State hypotheses, controls, '
    'evidence requirements and stopping conditions. Never claim experiments were run. '
    'Return a Chinese experiment plan. Do not reveal or request secrets.')


class Runtime:
    def __init__(self, store, repo=None, registry=None):
        self.store = store
        self.repo = Path(repo or os.environ.get('RASBOT_PRECISION_REPO', '../PrecisionTesting-main')).resolve()
        from .agents import AgentRegistry, PrecisionAgent, DemoAgent
        self.registry = registry or AgentRegistry([PrecisionAgent(self.repo), DemoAgent()])
        self.baseline = store.version({'name': 'baseline', 'instructions': DEFAULT_INSTRUCTIONS,
                                       'max_output_tokens': 2048, 'model_calls_per_task': 1})

    def catalog(self, agent_id='precision'):
        return self.registry.get(agent_id).catalog()

    def baseline_for(self, agent_id):
        if agent_id in ('precision', 'demo'): return self.baseline
        return self.store.version({'name': 'baseline', 'agent_id': agent_id, 'instructions': DEFAULT_INSTRUCTIONS})

    def create(self, domain, slug, version=None):
        agent = self.registry.get(domain)
        if agent.execution and (slug not in agent.catalog() or not agent.eligible(slug)):
            raise ValueError('Select a task from this Agent catalog')
        chosen = version or self.adopted(domain)
        with self.store.connect() as c:
            row = c.execute('SELECT body FROM versions WHERE id=?', (chosen,)).fetchone()
        if not row: raise ValueError('Unknown Harness version')
        owner = json.loads(row[0]).get('agent_id')
        if (owner and owner != domain) or (not owner and domain not in ('precision', 'demo')):
            raise ValueError('Harness version belongs to a different Agent')
        return self.store.create(domain, slug, chosen)

    def describe(self, task):
        agent = self.registry.get(task['domain'])
        return {**task, 'agent_id': agent.id, 'agent_name': agent.name, 'title': agent.title(task['slug'])}

    def adopted(self, domain='precision'):
        with self.store.connect() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='champions'").fetchone():
                champion = c.execute('SELECT version FROM champions WHERE domain=?', (domain,)).fetchone()
                if champion:
                    return champion[0]
        return self.baseline_for(domain)

    def advance(self, identity):
        task = self.store.get(identity)
        if task['state'] != 'queued':
            return task
        if not self.store.transition(identity, 'queued', 'preparing', {}):
            return self.store.get(identity)
        try:
            target = self.store.root / 'runs' / identity
            target.mkdir(parents=True, exist_ok=True)
            agent = self.registry.get(task['domain'])
            state, result = agent.prepare(self, task, target)
            self.store.transition(identity, 'preparing', state, result)
        except Exception as error:
            self.store.transition(identity, 'preparing', 'failed', {'error': str(error)})
        return self.store.get(identity)

    def model_plan(self, identity):
        """Compatibility entry point; all model requests go through OpenCode."""
        from .opencode_service import Service
        return Service(self).start(identity, planning=True)
