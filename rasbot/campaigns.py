"""Bounded persistent objectives orchestrating independently evaluated candidates."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from .core import now
from .evolution import LOCK, TERMINAL
from .evolution_selection import Selection
from .experience import Experience
from .preferences import evolution_model

STRATEGIES = (
    '优先检验执行指令改进，明确一个可验证的失败原因；避免无关改动。',
    '优先检验 Step 1 Skill 的分析步骤与工具使用流程改进。',
    '优先检验 Python 辅助脚本或生成脚本改进，保留独立验收标准。',
)


class Campaigns:
    def __init__(self, evolution):
        self.evo, self.store, self.runtime = evolution, evolution.store, evolution.runtime
        self.experience = Experience(self.store)
        with self.store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, body TEXT NOT NULL, created TEXT NOT NULL)')

    def list(self):
        with self.store.connect() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT body FROM campaigns ORDER BY created DESC')]

    def get(self, identity):
        with self.store.connect() as c:
            row = c.execute('SELECT body FROM campaigns WHERE id=?', (identity,)).fetchone()
        if not row:
            raise ValueError('Unknown evolution objective')
        return json.loads(row[0])

    def save(self, campaign):
        with self.store.connect() as c:
            c.execute('UPDATE campaigns SET body=? WHERE id=?', (json.dumps(campaign, ensure_ascii=False), campaign['id']))
        return campaign

    def create(self, objective, agent_id='precision', max_rounds=3, round_minutes=120,
               source_ids=None, slugs=None, model=None):
        with LOCK:
            if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 2000:
                raise ValueError('Describe an objective in 1–2000 characters')
            if type(max_rounds) is not int or not 1 <= max_rounds <= 12 or round_minutes not in (30, 60, 120):
                raise ValueError('Use 1–12 rounds and 30/60/120 minutes per round')
            if any(x['agent_id'] == agent_id and x['state'] in ('active', 'stopping', 'paused', 'needs_attention') for x in self.list()):
                raise ValueError('Finish or stop the existing objective for this Agent first')
            agent = self.runtime.registry.get(agent_id)
            if not getattr(agent, 'file_evolution', False):
                raise ValueError('Agent has no candidate development adapter')
            selected = Selection(self.runtime, agent_id).recommend()
            source_ids = source_ids if source_ids is not None else selected['source_ids']
            slugs = slugs if slugs is not None else selected['slugs']
            if not isinstance(source_ids, list) or not source_ids or len(source_ids) > 10:
                raise ValueError('Select 1–10 diagnosis tasks')
            if not isinstance(slugs, list) or not 2 <= len(slugs) <= 3 or len(set(slugs)) != len(slugs):
                raise ValueError('Select 2–3 distinct evaluation tasks')
            if any(s not in selected['pool'] or not agent.eligible(s) for s in slugs):
                raise ValueError('Evaluation tasks must belong to the fixed pool')
            sources = [self.store.get(i) for i in source_ids]
            if any(t['domain'] != agent_id or t['state'] not in ('generated', 'validation_failed', 'engine_failed', 'cancelled') for t in sources):
                raise ValueError('Diagnosis tasks must be terminal and belong to this Agent')
            if not set(slugs) - {t['slug'] for t in sources}:
                raise ValueError('At least one evaluation task must be absent from diagnosis')
            model = evolution_model(self.store, self.evo.engine.client, model)
            item = {'id': uuid.uuid4().hex, 'agent_id': agent_id, 'objective': objective.strip(),
                    'state': 'active', 'max_rounds': max_rounds, 'round_minutes': round_minutes,
                    'model': model, 'source_ids': source_ids, 'slugs': slugs, 'runs': [],
                    'current_run': None, 'created': now(), 'no_gain': 0,
                    'deadline': (datetime.now(timezone.utc) + timedelta(minutes=max_rounds * round_minutes + 1)).isoformat(),
                    'strategy': 'bounded-sequential-hypotheses-and-archive-v1'}
            with self.store.connect() as c:
                c.execute('INSERT INTO campaigns VALUES(?,?,?)', (item['id'], json.dumps(item, ensure_ascii=False), item['created']))
            return item

    def control(self, identity, action):
        with LOCK:
            item = self.get(identity)
            if action == 'resume':
                if item['state'] not in ('paused', 'needs_attention'):
                    raise ValueError('Only a paused objective can resume')
                if datetime.now(timezone.utc) >= datetime.fromisoformat(item['deadline']):
                    raise ValueError('Objective budget expired; create a new objective')
                item.update(state='active', last_error=None)
            elif action in ('pause', 'stop'):
                if item['state'] not in ('active', 'paused', 'needs_attention', 'stopping'):
                    return item
                item.update(state='stopping', stop_state='paused' if action == 'pause' else 'stopped')
            else:
                raise ValueError('Unknown objective action')
            return self.save(item)

    def tick(self, identity):
        with LOCK:
            item = self.get(identity)
            if item['state'] not in ('active', 'stopping'):
                return item
            # Reconcile by durable ownership before creating: crash after evolution.create
            # but before saving current_run must not duplicate a candidate or budget.
            owned = [r for r in self.evo.list() if r.get('campaign_context', {}).get('campaign_id') == identity]
            owned.sort(key=lambda r: r['campaign_context']['round_index'])
            item['runs'] = [r['id'] for r in owned]
            active = next((r for r in owned if r['state'] not in TERMINAL), None)
            item['current_run'] = active['id'] if active else None
            for run in owned:
                if run['state'] in TERMINAL:
                    self.experience.record(run)
            expired = datetime.now(timezone.utc) >= datetime.fromisoformat(item['deadline'])
            if expired:
                item.update(state='stopping', stop_state='budget_exhausted')
            if item['state'] == 'stopping':
                if active:
                    run = self.evo.cancel(active['id'])
                    if run['state'] not in TERMINAL:
                        return self.save(item)
                    self.experience.record(run)
                    item['acknowledged_run'] = run['id']
                item.update(state=item.get('stop_state', 'paused'), current_run=None)
                return self.save(item)
            if active:
                return self.save(item)
            if owned and owned[-1]['state'] in ('failed', 'inconclusive', 'cancelled'):
                # Resume acknowledges the last failed round, it never replays it.
                if item.get('acknowledged_run') != owned[-1]['id']:
                    item.update(state='needs_attention', acknowledged_run=owned[-1]['id'],
                                last_error=owned[-1].get('reason', 'Last experiment did not produce comparable evidence'))
                    return self.save(item)
            if len(owned) >= item['max_rounds']:
                item.update(state='budget_exhausted', current_run=None)
                return self.save(item)
            item['no_gain'] = 0
            for run in reversed(owned):
                if run['state'] == 'promoted':
                    break
                item['no_gain'] += 1
            if item['no_gain'] >= 3:
                item.update(state='stopped_no_gain')
                return self.save(item)
            if any(r['state'] not in TERMINAL and r.get('agent_id', 'precision') == item['agent_id'] for r in self.evo.list()):
                return self.save(item)  # A manually initiated round owns this Agent slot.
            index = len(owned)
            donor = None
            if index % 2:
                donors = [r for r in reversed(owned) if r['state'] == 'rejected' and r.get('candidate')]
                donor = donors[0]['candidate'] if donors else None
            context = {'campaign_id': identity, 'round_index': index, 'objective': item['objective'],
                       'hypothesis': STRATEGIES[index % len(STRATEGIES)],
                       'experiences': self.experience.recall(item['agent_id'])}
            minutes_left = (datetime.fromisoformat(item['deadline']) - datetime.now(timezone.utc)).total_seconds() / 60
            if minutes_left < 30:
                item.update(state='budget_exhausted')
                return self.save(item)
            budget = max(m for m in (30, 60, 120) if m <= min(item['round_minutes'], minutes_left))
            run = self.evo.create(item['source_ids'], item['slugs'], item['model'], budget,
                                  item['agent_id'], development=True, proposal_parent=donor,
                                  campaign_context=context)
            item.update(current_run=run['id'], runs=item['runs'] + [run['id']])
            return self.save(item)

    def tick_all(self):
        for item in self.list():
            if item['state'] in ('active', 'stopping'):
                try:
                    self.tick(item['id'])
                except Exception as error:
                    with LOCK:
                        latest = self.get(item['id'])
                        # Keep stopping retryable until cancellation is confirmed.
                        latest.update(last_error=str(error))
                        if latest['state'] != 'stopping':
                            latest['state'] = 'needs_attention'
                        self.save(latest)
