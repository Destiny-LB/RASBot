"""Independent, fixed input-design probes. No claims about sampled hardware values."""
import math
VERSION = 'precision-risk-design-v2'
SUPPORTED = ('aclnnExpm1', 'aclnnLog1p', 'aclnnHardtanh')

def number(x):
    return type(x) in (int, float) and math.isfinite(x)

DTYPES={'float':'fp32','float32':'fp32','float16':'fp16','half':'fp16','bfloat16':'bf16'}

def bounds(entry):
    raw=entry.get('range_values')
    if isinstance(raw,dict) and raw.get('name')=='constant':raw=raw.get('value')
    if isinstance(raw,list) and raw and all(isinstance(v,dict) and v.get('name')=='constant' for v in raw):
        raw=[v.get('value') for v in raw]
    if number(raw): return raw,raw
    if isinstance(raw,list) and raw and all(number(v) for v in raw): return min(raw),max(raw)
    return None  # Unknown distributions never imply a hit.

def evaluate(slug, suite):
    op=next((op for op in SUPPORTED if slug.endswith('-'+op)),None)
    if op is None: return {'version':VERSION,'status':'unsupported','score':None,'checks':[]}
    names=['fp32','low_precision','nonaligned_length','multiple_dimensions','near_zero']
    names += ['negative_tail','positive_growth'] if op=='aclnnExpm1' else ['above_minus_one','positive_values'] if op=='aclnnLog1p' else ['lower_clip_crossing','upper_clip_crossing']
    hits={k:[] for k in names};unknown=set()
    for i,c in enumerate(suite if isinstance(suite,list) else []):
        if not isinstance(c,dict) or not isinstance(c.get('inputs'),list):continue
        inputs=[v for v in c['inputs'] if isinstance(v,dict)]
        tensor=next((v for v in inputs if v.get('type')=='tensor'),None)
        if not tensor:continue
        shape=tensor.get('shape');dtype=tensor.get('dtype');dtype=DTYPES.get(dtype,dtype)
        if not isinstance(shape,list) or not all(type(v)is int and v>0 for v in shape):continue
        n=math.prod(shape);b=bounds(tensor)
        lo,hi=b if b else (None,None)
        if b is None:unknown.update(names[4:])
        tests={'fp32':dtype=='fp32','low_precision':dtype in ('fp16','bf16'),
               'nonaligned_length': n>1 and n%32!=0,'multiple_dimensions':len(shape)>=2,
               'near_zero': bool(b and -1e-4<=lo<=hi<=1e-4 and (lo<0 or hi>0))}
        if op=='aclnnExpm1':tests.update(negative_tail=bool(b and hi<=-10),positive_growth=bool(b and lo>=5))
        elif op=='aclnnLog1p':tests.update(above_minus_one=bool(b and -1<lo<=hi<=-.99),positive_values=bool(b and lo>=1))
        else:
            scalars={v.get('name'):bounds(v) for v in inputs if v.get('type')=='scalar'}
            a,z=scalars.get('clipValueMin'),scalars.get('clipValueMax')
            if a is None or z is None:unknown.update(['lower_clip_crossing','upper_clip_crossing'])
            fixed=bool(a and z and a[0]==a[1] and z[0]==z[1] and a[0]<z[0])
            tests.update(lower_clip_crossing=bool(fixed and b and lo<a[0]<hi),upper_clip_crossing=bool(fixed and b and lo<z[0]<hi))
        for k,ok in tests.items():
            if ok and len(hits[k])<5:hits[k].append(c.get('id',i))
    checks=[{'id':k,'hit':bool(v),'status':'hit' if v else 'not_measured' if k in unknown else 'not_hit','case_ids':v} for k,v in hits.items()]
    return {'version':VERSION,'profile':op,'status':'partially_measured' if any(c['status']=='not_measured' for c in checks) else 'measured',
            'score':sum(x['hit'] for x in checks)/len(checks),
            'score_semantics':'confirmed_coverage_lower_bound',
            'possible_range':[sum(x['hit'] for x in checks)/len(checks),sum(x['hit'] or x['status']=='not_measured' for x in checks)/len(checks)],
            'checks':checks,'scope':'Fixed input-specification risk probes; not sampled coverage or defect detection'}


def consistency(suite,ledger):
    """Fraction of cases with nonempty intent and resolvable, reciprocal references.
    Ledger structural validity remains a separate fraction so empty/extra rows cannot hide errors.
    """
    import re
    if not isinstance(suite,list) or not suite or not isinstance(ledger,dict) or not isinstance(ledger.get('triggers'),list):return 0.0
    rows=ledger['triggers'];triggers={}
    for t in rows:
        if isinstance(t,dict) and isinstance(t.get('id'),str):triggers.setdefault(t['id'],[]).append(t)
    cases={};duplicates=set()
    for c in suite:
        if isinstance(c,dict) and type(c.get('id'))is int:
            if c['id'] in cases:duplicates.add(c['id'])
            cases[c['id']]=c
    refs={};valid=0
    code=ledger.get('code_triggers',{})
    if not isinstance(code,dict):code={}
    for c in suite:
        if not isinstance(c,dict):continue
        identity=c.get('id');values=c.get('trigger_library_ref');ok=type(identity)is int and identity not in duplicates and isinstance(c.get('generate_intent'),str) and bool(c['generate_intent'].strip())
        links=set()
        if not isinstance(values,list) or not values:ok=False;values=[]
        for ref in values:
            match=re.fullmatch(r'(TRIGGER-|CODE-)([\w.-]+):\s*(\S.*)',ref) if isinstance(ref,str) else None
            if not match:ok=False;continue
            key=match[2]
            if match[1]=='CODE-':ok=ok and (key in code or 'CODE-'+key in code)
            else:
                links.add(key);ts=triggers.get(key,[])
                ok=ok and len(ts)==1 and isinstance(ts[0].get('actual_case_ids'),list) and identity in ts[0]['actual_case_ids'] and ts[0].get('status')=='applicable'
        if type(identity)is int:refs[identity]=links
        valid+=bool(ok)
    good_rows=0
    for t in rows:
        if not isinstance(t,dict):continue
        key=t.get('id');ids=t.get('actual_case_ids',[]);status=t.get('status')
        if not isinstance(key,str) or len(triggers[key])!=1 or not isinstance(ids,list) or any(type(i)is not int for i in ids):continue
        ok=status in ('applicable','skipped','not_testable') and (bool(ids) if status=='applicable' else not ids)
        ok=ok and len(set(ids))==len(ids) and all(i in cases and key in refs.get(i,set()) for i in ids)
        good_rows+=bool(ok)
    return (valid/len(suite)) * (good_rows/len(rows) if rows else 1)


def diversity(suite):
    """Typed canonicalization retains NaN/Infinity probes without JSON collisions.
    IDs, intent and repeat claims outside inputs do not create diversity credit.
    """
    def canonical(value):
        if isinstance(value,dict):return ('dict',tuple(sorted((k,canonical(v)) for k,v in value.items())))
        if isinstance(value,list):return ('list',tuple(canonical(v) for v in value))
        if isinstance(value,float) and not math.isfinite(value):return ('special_float','nan' if math.isnan(value) else '+inf' if value>0 else '-inf')
        if value is None:return ('null',)
        return (type(value).__name__,value)
    if not isinstance(suite,list) or not suite:return 0.0
    try:
        signatures=[canonical(c['inputs']) for c in suite]
        return len(set(signatures))/len(signatures)
    except (TypeError,KeyError,ValueError):return None


def supported(slug):
    return isinstance(slug,str) and any(slug.endswith("-"+op) for op in SUPPORTED)
