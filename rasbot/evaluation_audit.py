"""Offline baseline snapshot + shadow audit. Reads SQLite without mutating scores."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .analysis import analyze_task


def audit(data, output):
    data, output = Path(data).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).parent
    snapshot = output / 'source'
    snapshot.mkdir()
    hashes = {}
    # Exact code snapshot excludes configuration, runtime logs and credentials.
    for file in sorted(source.glob('*.py')):
        raw = file.read_bytes()
        (snapshot / file.name).write_bytes(raw)
        hashes[file.name] = hashlib.sha256(raw).hexdigest()
    report = {'created': datetime.now(timezone.utc).isoformat(), 'mode': 'shadow-only',
              'source_sha256': hashes, 'tasks': [], 'versions': [], 'evolution': [],
              'limits': ['No hardware execution', 'No promotion or historical score changes',
                         'No proof of numerical coverage; runtime environment is not fully frozen']}
    c = sqlite3.connect((data / 'rasbot.db').as_uri() + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    try:
        c.execute('BEGIN')
        report['versions'] = [dict(r) for r in c.execute('SELECT * FROM versions')]
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'champions' in tables: report['champions'] = [dict(r) for r in c.execute('SELECT * FROM champions')]
        if 'evolution_runs' in tables:
            for r in c.execute('SELECT body FROM evolution_runs'):
                run = json.loads(r[0])
                report['evolution'].append({k:run[k] for k in ('id','state','baseline','candidate','scores','evaluator_id') if k in run})
        for row in c.execute("SELECT * FROM tasks WHERE state='generated'"):
            task = dict(row);task['result'] = json.loads(task['result'])
            task['events'] = [dict(e) for e in c.execute('SELECT * FROM events WHERE task_id=? ORDER BY seq',(task['id'],))]
            result = analyze_task(task)
            result.update(slug=task['slug'], harness=task['version'], integrity={})
            validation = task['result'].get('validation', {})
            artifacts = output / 'artifacts' / task['id']
            artifacts.mkdir(parents=True)
            for key in ('suite','atk_input'):
                path = Path(validation.get(key, ''))
                valid = path.is_file() and path.resolve().is_relative_to(data)
                match = False
                if valid:
                    raw = path.read_bytes();actual = hashlib.sha256(raw).hexdigest()
                    match = actual == validation.get(key+'_sha256')
                    (artifacts / (key+'.json')).write_bytes(raw)
                result['integrity'][key] = {'present_in_data_root':valid,'matches_recorded_hash':match}
            ledger = Path(task['result']['workspace']) / '01_generate/report/trigger_coverage.json'
            if ledger.is_file() and ledger.resolve().is_relative_to(data):
                shutil.copyfile(ledger, artifacts / 'trigger_coverage.json')
            report['tasks'].append(result)
    finally:
        c.close()
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 评价升级：基线快照与影子观察', '', '本报告不修改历史分数，不触发晋升。', '',
             '|任务|Harness|规则数|重复规格数|引用问题数|输入摘要一致|','|---|---|---:|---:|---:|---|']
    for t in report['tasks']:
        d=t.get('input_diversity',{});q=t['quality']
        lines.append(f"|{t['slug']} / {t['task_id'][:8]}|{t['harness']}|{d.get('case_count','N/A')}|{d.get('duplicate_excess','N/A')}|{q.get('issue_count','N/A')}|{all(x['matches_recorded_hash'] for x in t['integrity'].values())}|")
    lines += ['', '限制：规格差异不等于有效覆盖；引用一致不等于意图正确；没有硬件缺陷检出证据。']
    (output / 'report.md').write_text('\n'.join(lines), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data', default='.rasbot')
    parser.add_argument('--output', required=True)
    args=parser.parse_args()
    r=audit(args.data,args.output)
    print(f"Shadow audit saved: {args.output}; tasks={len(r['tasks'])}")
