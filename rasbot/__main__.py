import argparse
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .core import Store
from .runtime import Runtime


def serve(runtime, port):
    token = secrets.token_urlsafe(32)
    from .opencode_service import Service
    from .settings import Settings
    settings = Settings(runtime.store)
    engine = Service(runtime)
    from .evolution import Evolution
    evolution = Evolution(runtime, engine)
    from .campaigns import Campaigns
    campaigns = Campaigns(evolution)
    from .evolution_selection import Selection
    selection = Selection(runtime)
    selection.pool()
    try:
        settings.start(engine)
    except Exception:
        # Stay bound to the intended endpoint even if its process failed to start.
        try:
            engine.client = settings.guard(settings.client())
        except Exception:
            class Unavailable:
                url = ''
                def request(self, *args, **kwargs):
                    raise RuntimeError('无法加载执行引擎，请在平台设置中重新配置。')
            engine.client = Unavailable()

    stopping = threading.Event()
    def evolve():
        while not stopping.wait(5):
            with settings.lock:
                campaigns.tick_all()
            for item in evolution.list():
                try:
                    with settings.lock:
                        evolution.tick(item['id'])
                except Exception as error:
                    from .evolution import LOCK
                    with LOCK:
                        current = evolution.get(item['id'])
                        current['last_error'] = str(error)
                        evolution.save(current)
    threading.Thread(target=evolve, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def parse_request(self):
            if not super().parse_request():
                return False
            # Never trust DNS resolution or forwarded headers: only the actual
            # loopback authority and listening port can address this service.
            port = self.server.server_port
            authorities = {f'127.0.0.1:{port}', f'localhost:{port}'}
            if port == 80:
                authorities.update(('127.0.0.1', 'localhost'))
            hosts = self.headers.get_all('Host', [])
            origins = self.headers.get_all('Origin', [])
            host = hosts[0].lower() if len(hosts) == 1 else ''
            allowed_origins = {f'http://{host}'}
            if port == 80 and host in authorities:
                name = host.removesuffix(':80')
                allowed_origins.update((f'http://{name}', f'http://{name}:80'))
            if (host not in authorities or len(origins) > 1 or
                    (origins and origins[0].lower() not in allowed_origins)):
                self.close_connection = True
                self.reply({'error': 'Invalid Host or Origin'}, 403)
                return False
            return True

        def reply(self, data, status=200):
            raw = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/':
                raw = Path(__file__).with_name('web.html').read_text(encoding='utf-8').replace('__TOKEN__', token).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(raw)
            elif path == '/api/state':
                snapshot = runtime.store.snapshot()
                snapshot['tasks'] = [runtime.describe(t) for t in snapshot['tasks']]
                self.reply({**snapshot, 'agents': runtime.registry.public(), 'catalog': runtime.catalog(),
                            'baseline': runtime.adopted(), 'model_backend': 'opencode'})
            elif path.startswith('/api/agents/') and path.endswith('/tasks'):
                try:
                    agent = runtime.registry.get(path.split('/')[3])
                    self.reply({'agent': agent.id, 'task_label': agent.task_label, 'description': agent.description,
                                'tasks': [{'id': k, 'title': agent.title(k)} for k in agent.catalog()
                                          if not agent.execution or agent.eligible(k)]})
                except ValueError as e:
                    self.reply({'error': str(e)}, 400)
            elif path == '/api/campaigns':
                self.reply({'campaigns': campaigns.list()})
            elif path == '/api/experiences':
                agent_id = parse_qs(urlparse(self.path).query).get('agent_id', ['precision'])[0]
                self.reply({'experiences': campaigns.experience.list(agent_id)})
            elif path == '/api/settings':
                self.reply(settings.public())
            elif path == '/api/evolution':
                try:
                    query = parse_qs(urlparse(self.path).query)
                    result = evolution.page(int(query.get('page', ['1'])[0]), int(query.get('page_size', ['5'])[0]))
                except ValueError as e:
                    return self.reply({'error': str(e)}, 400)
                runs = result['runs']
                for run in runs:
                    adapter = runtime.registry.get(run.get('agent_id', 'precision'))
                    run.update(agent_id=adapter.id, agent_name=adapter.name, task_titles={k: adapter.title(k) for k in run['slugs']})
                self.reply(result)
            elif path == '/api/evolution/recommendation':
                try:
                    agent_id = parse_qs(urlparse(self.path).query).get('agent_id', ['precision'])[0]
                    query = parse_qs(urlparse(self.path).query, keep_blank_values=True)
                    previous_sources = query.get('source_id', []) if query.get('rotate') == ['1'] else None
                    previous_slugs = query.get('slug', []) if previous_sources is not None else None
                    self.reply(Selection(runtime, agent_id).recommend(previous_sources, previous_slugs))
                except ValueError as e:
                    self.reply({'error': str(e)}, 400)
            elif path == '/api/analysis':
                from .analysis import analyze_task
                try:
                    identity = parse_qs(urlparse(self.path).query).get('task_id', [''])[0]
                    self.reply(analyze_task(runtime.store.get(identity)))
                except ValueError as e:
                    self.reply({'error': str(e)}, 400)
            elif path == '/api/versions':
                from .version_audit import audit_versions
                versions = audit_versions(runtime.store, runtime.adopted(), evolution.list(),
                            {a.id: runtime.adopted(a.id) for a in runtime.registry.adapters.values()})
                for version in versions:
                    adapter = runtime.registry.get(version['agent_id'])
                    version['agent_name'] = adapter.name
                    for evaluation in version['evaluations']:
                        for trial in evaluation['trials']:
                            trial['title'] = adapter.title(trial['slug'])
                self.reply({'versions': versions})
            elif path == '/api/settings/models':
                from .preferences import models
                try:
                    self.reply({'models': models(engine.client)})
                except Exception as e:
                    self.reply({'error': str(e)}, 400)
            elif path == '/api/engine':
                try:
                    info = engine.client.request('GET', '/api/info')
                    self.reply({'connected': True, 'version': info.get('version'), 'web_url': engine.client.url})
                except Exception as e:
                    self.reply({'connected': False, 'enabled': not settings.disconnected.exists(), 'error': str(e), 'web_url': engine.client.url})
            elif path.startswith('/api/tasks/'):
                try:
                    self.reply(runtime.describe(runtime.store.get(path.rsplit('/', 1)[-1])))
                except ValueError as e:
                    self.reply({'error': str(e)}, 404)
            else:
                self.reply({'error': 'Not found'}, 404)

        def do_POST(self):
            with settings.lock:
                self.handle_post()

        def handle_post(self):
            if self.headers.get('X-RASBot-Token') != token:
                return self.reply({'error': 'Invalid request token'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(length))
                path = urlparse(self.path).path
                if path in ('/api/settings/connect', '/api/settings/disconnect'):
                    result = settings.connection(engine, enabled=path.endswith('/connect'))
                elif path == '/api/campaigns/start':
                    result = campaigns.create(data['objective'], data.get('agent_id', 'precision'),
                        data.get('max_rounds', 3), data.get('round_minutes', 120),
                        data.get('source_ids'), data.get('slugs'), data.get('model'))
                elif path == '/api/campaigns/control':
                    result = campaigns.control(data['id'], data['action'])
                elif path == '/api/evolution/start':
                    agent_id = data.get('agent_id', 'precision')
                    proposed = Selection(runtime, agent_id).recommend()
                    sources = data.get('source_ids', proposed['source_ids'])
                    slugs = data.get('slugs', proposed['slugs'])
                    if any(s not in proposed['pool'] for s in slugs):
                        raise ValueError('Evaluation task is outside the fixed pool')
                    if 'session_minutes' in data:
                        raise ValueError('Use round_minutes (60, 120 or 240); session_minutes is no longer supported')
                    result = evolution.create(sources, slugs, data.get('model'), data.get('round_minutes', 120), agent_id,
                                                  development=data.get('development', getattr(runtime.registry.get(agent_id), 'file_evolution', False)))
                    result['selection'] = {'policy': proposed['policy'], 'pool_version': proposed['pool_version'],
                                           'pool': proposed['pool'], 'reason': proposed['reason'],
                                           'adjusted': sources != proposed['source_ids'] or slugs != proposed['slugs']}
                    evolution.save(result)
                elif path == '/api/evolution/tick':
                    result = evolution.tick(data['id'])
                elif path == '/api/evolution/cancel':
                    result = evolution.cancel(data['id'])
                elif path == '/api/evolution/rollback':
                    result = evolution.rollback(data['id'])
                elif path == '/api/settings/model':
                    from .preferences import save_model
                    result = save_model(runtime.store, engine.client, data['model'])
                elif path == '/api/tasks':
                    result = {'id': runtime.create(data.get('agent_id', data.get('domain')), data.get('task_key', data.get('slug', 'demo')), data.get('version'))}
                elif path == '/api/advance':
                    result = runtime.advance(data['id'])
                elif path == '/api/plan':
                    result = engine.start(data['id'], planning=True)
                elif path == '/api/engine/start':
                    result = engine.start(data['id'])
                elif path == '/api/panel/open':
                    result = engine.panel_open(data['id'])
                elif path == '/api/panel/view':
                    result = engine.panel_view(data['id'])
                elif path == '/api/panel/send':
                    result = engine.panel_send(data['id'], data['text'])
                elif path == '/api/panel/permission':
                    result = engine.panel_permission(data['id'], data['request_id'], data['reply'])
                elif path == '/api/engine/sync':
                    result = engine.sync(data['id'])
                elif path == '/api/engine/cancel':
                    result = engine.cancel(data['id'])
                elif path == '/api/engine/repair':
                    result = engine.repair_generation(data['id'])
                else:
                    return self.reply({'error': 'Not found'}, 404)
                self.reply(result)
            except (ValueError, KeyError, TypeError, RuntimeError) as e:
                self.reply({'error': str(e)}, 400)
            except Exception:
                self.reply({'error': 'Internal failure; check local state and logs'}, 500)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'RASBot: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description='RASBot local reliability workbench')
    parser.add_argument('command', choices=['serve', 'demo', 'agent-bundle', 'agent-run'], nargs='?', default='serve')
    parser.add_argument('--task')
    parser.add_argument('--engine', choices=['opencode'], default='opencode')
    parser.add_argument('--model', default=None)
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--data', default='.rasbot')
    parser.add_argument('--repo', default=None)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    runtime = Runtime(Store(args.data), args.repo)
    if args.command in ('agent-bundle', 'agent-run'):
        from .agent_runtime import bundle, execute
        if not args.task:
            parser.error('--task is required')
        result = (bundle(runtime, args.task, args.engine, args.model) if args.command == 'agent-bundle'
                  else execute(runtime, args.task, args.engine, args.model, args.timeout))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == 'demo':
        identity = runtime.create('demo', 'lifecycle')
        print(json.dumps(runtime.advance(identity), ensure_ascii=False, indent=2))
    else:
        serve(runtime, args.port)


if __name__ == '__main__':
    main()
