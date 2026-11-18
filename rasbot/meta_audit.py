"""Read-only re-evaluation of all terminal tasks and paired trials."""
import argparse
import json
import sqlite3
from pathlib import Path
from .meta_evaluation import evaluate, compare
from .evaluation_policy import EVALUATOR_ID as VERSION


def audit(data, repo, output):
    data=Path(data).resolve();output=Path(output)
    c=sqlite3.connect((data/'rasbot.db').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    report={'version':VERSION,'mode':'shadow','tasks':[],'comparisons':[]}
    try:
        c.execute('BEGIN')
        for row in c.execute("SELECT * FROM tasks WHERE domain='precision' AND state IN ('generated','validation_failed','engine_failed','cancelled')"):
            task=dict(row);task['result']=json.loads(task['result'])
            task['events']=[dict(e) for e in c.execute('SELECT * FROM events WHERE task_id=? ORDER BY seq',(task['id'],))]
            report['tasks'].append({'id':task['id'],'slug':task['slug'],'original_state':task['state'],
                                    'evaluation':evaluate(task,repo,data/'tool-deps')})
        by_id={t['id']:t['evaluation'] for t in report['tasks']}
        for row in c.execute('SELECT body FROM evolution_runs'):
            run=json.loads(row[0]);groups={}
            for trial in run.get('trials',[]):
                key=(trial['slug'],trial.get('replicate',0))
                if trial['task_id'] in by_id:groups.setdefault(key,{})[trial['role']]=by_id[trial['task_id']]
            pairs=[(slug+' / '+str(rep),v['baseline'],v['candidate']) for (slug,rep),v in groups.items() if set(v)=={'baseline','candidate'}]
            report['comparisons'].append({'id':run['id'],'original_state':run['state'],'comparison':compare(pairs)})
    finally:c.close()
    output.mkdir(parents=True,exist_ok=False)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['RASBot 影子元评价：不修改历史结果或采用版本。','风险覆盖是否已测以各任务 evidence 为准；本次审计不修改晋升结论，不代表硬件效果验证。','']
    for t in report['tasks']:
        q=t['evaluation']['quality'];lines.append(f"{t['slug']} [{t['id'][:8]}] 原状态={t['original_state']}；已测分={q['measured_points']}/{q['measured_maximum']}；总分区间={q['possible_range']}")
    (output/'report.txt').write_text('\n'.join(lines),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--repo',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=audit(a.data,a.repo,a.output);print('Shadow tasks:',len(r['tasks']))
