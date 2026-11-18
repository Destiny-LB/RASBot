"""Quality-only promotion; runtime cost is not reliability evidence."""
import math
from .meta_evaluation import WEIGHTS
from .evaluation_policy import QUALITY_POLICY, PROMOTION_POLICY

def decide(trials, slugs, policy):
    from .evaluation_policy import EVALUATOR_ID as evaluator
    from .risk_profile import supported
    scope_keys={}
    for slug in slugs:
        rows=[t for t in trials if t['slug']==slug]
        no_profile=not supported(slug) and all(t.get('meta_evaluation',{}).get('quality',{}).get('metrics',{}).get('risk_coverage') is None for t in rows)
        scope_keys[slug]=tuple(k for k in WEIGHTS if k!='risk_coverage' or not no_profile)
    def result(state, reason, **extra):
        return dict(state=state,reason=reason,policy_version=QUALITY_POLICY,
                    scope='generation design quality; no hardware effect claim',
                    validated_stages=['01_generate'],unvalidated_stages=['02_atk_run','03_analyze'],
                    promotion_policy=PROMOTION_POLICY,**extra)
    groups={}
    for t in trials:
        key=(t['slug'],t.get('replicate',0));pair=groups.setdefault(key,{})
        if t['role'] not in ('baseline','candidate') or t['role'] in pair:
            return result('inconclusive','invalid_pair')
        pair[t['role']]=t
    rounds={r for _,r in groups}
    if not slugs or rounds not in ({0},{0,1}) or set(groups)!={(s,r) for s in slugs for r in rounds} or any(set(p)!={'baseline','candidate'} for p in groups.values()):
        return result('inconclusive','incomplete_pairs')
    # Incomplete or corrupted evidence takes precedence over any behavioral verdict.
    for t in trials:
        contract=t.get('toolchain_contract') or {}
        if contract.get('passed') is False and (contract.get('status')=='error' or contract.get('reason') in ('budget_exhausted','integrity_violation','infrastructure_error','trusted_contract_failed')):
            return result('inconclusive','toolchain_evidence_unavailable',cause=contract.get('reason','probe_error'),slug=t['slug'],role=t['role'])
        if t.get('manual_intervention') or not t.get('comparable') or t.get('meta_evaluation',{}).get('validity',{}).get('eligible') is not True:
            return result('inconclusive','untrusted_evidence',slug=t['slug'],role=t['role'])
    for t in trials:
        if t['role']=='candidate' and type(t.get('passed')) is not bool:
            return result('inconclusive','candidate_acceptance_unmeasured',slug=t['slug'])
        if t.get('passed') is True and t.get('toolchain_required') and not t.get('toolchain_contract'):
            return result('inconclusive','required_contract_not_run',slug=t['slug'],role=t['role'])
    pairs=[];regressions=[];invalid=[]
    for (slug,rep),pair in sorted(groups.items()):
        required=scope_keys[slug]
        values={}
        for role,t in pair.items():
            contract=t.get('toolchain_contract')
            if contract and contract.get('passed') is not True:
                return result('rejected' if role=='candidate' else 'inconclusive','toolchain_contract_failed',slug=slug,role=role)
            if role=='candidate' and t['passed'] is not True:
                return result('rejected','candidate_acceptance_failed',slug=slug)
            e=t.get('meta_evaluation',{})
            if t.get('manual_intervention') or not t.get('comparable') or e.get('validity',{}).get('eligible') is not True or e.get('evaluator_version')!=evaluator:
                return result('inconclusive','untrusted_evidence',slug=slug,role=role)
            m=e.get('quality',{}).get('metrics',{})
            missing=[k for k in required if type(m.get(k))not in (int,float) or not math.isfinite(m[k]) or not 0<=m[k]<=1]
            if missing:return result('inconclusive','unmeasured_metrics',missing_metrics=missing,slug=slug,role=role)
            values[role]=m
        b,c=values['baseline'],values['candidate']
        delta={k:c[k]-b[k] for k in required}
        for k,v in delta.items():
            if v < -1e-9:regressions.append(dict(slug=slug,replicate=rep,metric=k,delta=v))
        if c['valid_rules']<1 or c['deliverables']<1:invalid.append(dict(slug=slug,replicate=rep))
        score=lambda m:sum(100*WEIGHTS[k]*m[k] for k in required)
        pairs.append(dict(slug=slug,replicate=rep,baseline_score=score(b),candidate_score=score(c),
                          gain=score(c)-score(b),metric_deltas=delta))
    gains=[sum(p['gain'] for p in pairs if p['replicate']==rep)/len(slugs) for rep in sorted(rounds)]
    evidence=dict(pairs=pairs,mean_gains=gains,regressions=regressions,invalid_candidates=invalid,
                  measured_maximum=sum(sum(100*WEIGHTS[k] for k in scope_keys[s]) for s in slugs)/len(slugs),minimum_gain=1.0,
                  metric_scope={s:list(keys) for s,keys in scope_keys.items()},threshold_calibration='not_calibrated',
                  unmeasured_risk_tasks=[s for s,keys in scope_keys.items() if 'risk_coverage' not in keys])
    if rounds=={0,1}:
        evidence['baseline_repeat_absolute_score_deltas']={s:abs(next(p['baseline_score'] for p in pairs if p['slug']==s and p['replicate']==1)-next(p['baseline_score'] for p in pairs if p['slug']==s and p['replicate']==0)) for s in slugs}
    if invalid:return result('rejected','candidate_requirements_failed',**evidence)
    # Soft metric regressions remain visible; only hard acceptance gates veto.
    # Each confirmation round must independently demonstrate aggregate benefit.
    if any(g<1 for g in gains):return result('rejected','insufficient_quality_gain',candidate_disposition='retained_unproven',**evidence)
    if rounds=={0}:return result('confirming','confirmation_required',**evidence)
    return result('promoted','confirmed_quality_gain',basis='generation_design_quality',**evidence)


def summary(run):
    """Stable aggregate for search/memory; no held-out identities or raw outputs."""
    d=run.get('decision') or {};pairs=d.get('pairs',[])
    if not pairs or not all('gain' in p for p in pairs):return None
    metrics={k:sum(p.get('metric_deltas',{}).get(k,0) for p in pairs)/len(pairs) for k in WEIGHTS}
    return dict(basis=d.get('basis'),outcome=d.get('state',run.get('state')),
                promotion_policy=d.get('promotion_policy'),validated_stages=d.get('validated_stages',[]),
                failure_cause=d.get('cause'),cost_role='budget_and_diagnostics_only',
                policy_version=d.get('policy_version'),evaluator_id=run.get('evaluator_id'),
                mean_gain=sum(p['gain'] for p in pairs)/len(pairs),metric_deltas=metrics,
                regression_count=len(d.get('regressions',[])),reason=d.get('reason'),
                confirmation_required=d.get('confirmation_required',False) or d.get('state')=='confirming')
