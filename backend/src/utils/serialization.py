import hashlib, json
def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
def dataset_dict(d):
    return {'id':d.id, 'name':d.name, 'source':d.source, 'rows':len(d.records), 'checksum':d.checksum, 'created_at':d.created_at,
            'kind':d.kind, 'month':d.month, 'batch_no':d.batch_no, 'superseded':d.superseded}
def job_dict(j, stale=False):
    return {**{k:getattr(j,k) for k in ['id','name','dataset_id','params','status','result','error','approved','created_at','finished_at']}, 'stale':stale}
def report_dict(r):
    return {k:getattr(r,k) for k in ['id','name','job_id','destination','interval_seconds','next_run','enabled']}
def delivery_dict(d):
    return {k:getattr(d,k) for k in ['id','report_id','created_at','checksum','filename','destination']}
def ingest_dict(b):
    return {'id':b.id, 'month':b.month, 'source':b.source, 'rows':b.rows, 'status':b.status, 'errors':b.errors, 'effects':b.effects, 'created_at':b.created_at}
def publish_dict(o):
    return {'id':o.id, 'month':o.month, 'batch_no':o.batch_no, 'status':o.status, 'error':o.error, 'checks':o.checks,
            'dataset_id':o.dataset_id, 'created_at':o.created_at, 'published_at':o.published_at}
