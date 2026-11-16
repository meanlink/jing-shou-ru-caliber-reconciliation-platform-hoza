import time, json, random
from sqlalchemy import select, func
from src.config.database import Session
from migrations.initial import migrate
from src.models import User, Dataset, Job, Report, Delivery, Audit, IngestBatch, CumulativeRecord
from src.services.business import metadata, seed_records, analyze
from src.services import ledger as ledger_svc
from src.services.reports import deliver
from src.utils.security import hash_password
from src.utils.serialization import checksum
CHANNELS=(('直营内容',18500),('机构许可',11600),('合作渠道',14200))
def _daily_values(rng,days):
    values={}
    for channel,base in CHANNELS:
        for i in days:
            gross=round(base*rng.uniform(0.8,1.22),2)
            refunds=round(gross*rng.uniform(0.02,0.05),2)
            discount=round(gross*rng.uniform(0.05,0.11),2)
            fee=round(gross*0.018,2) if channel=='合作渠道' else 0.0
            values[(channel,i)]={'gross':gross,'refunds':refunds,'discount':discount,'recognized_net':round(gross-refunds-discount-fee,2),'visits':rng.randint(200,760)}
    return values
def _cumulative_rows(month,daily,skip=()):
    rows,cum=[],{}
    for day in sorted({d for _,d in daily}):
        for channel,_ in CHANNELS:
            if (channel,day) in skip or (channel,day) not in daily: continue
            acc=cum.setdefault(channel,{k:0 for k in ledger_svc.METRICS})
            for k,v in daily[(channel,day)].items(): acc[k]+=v
            rows.append({'day':f'{month}-{day:02d}','channel':channel,**{k:(round(acc[k],2) if k!='visits' else acc[k]) for k in ledger_svc.METRICS}})
    return rows
def seed_ledger(db,admin,m):
    if db.scalar(select(IngestBatch).where(IngestBatch.source.like('seed-ledger%'))): return
    rng=random.Random(202611)
    # 2026-10 完整账期：接账 → 发布第1批 → 迟到更正（同时改变相邻两日日账）→ 发布第2批，第1批随之失效
    month='2026-10'
    ledger_svc.ensure_month(db,month)
    daily=_daily_values(rng,range(1,32))
    b1=ledger_svc.ingest(db,month,_cumulative_rows(month,daily),'seed-ledger-202610',admin)
    o1=ledger_svc.create_publish_order(db,month,admin); ledger_svc.publish(db,o1)
    v1=db.get(Dataset,o1.dataset_id)
    params={p['key']:p['default'] for p in m.get('parameters',[])}
    result=analyze(v1.records,params); json.dumps(result,ensure_ascii=False,allow_nan=False)
    db.add(Job(name='试算 · 2026-10 第1批（更正前）',dataset_id=v1.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-7200,finished_at=time.time()-7195,approved=False))
    db.flush()
    rec=db.scalar(select(CumulativeRecord).where(CumulativeRecord.month==month,CumulativeRecord.channel=='合作渠道',CumulativeRecord.day=='2026-10-15'))
    fix=[{'day':'2026-10-15','channel':'合作渠道','gross':round(rec.gross+300.0,2),'refunds':rec.refunds,'discount':rec.discount,'recognized_net':round(rec.recognized_net+300.0,2),'visits':rec.visits}]
    ledger_svc.ingest(db,month,fix,'seed-ledger-correction',admin)
    o2=ledger_svc.create_publish_order(db,month,admin); ledger_svc.publish(db,o2)
    # 累计回退的更正整批拒收，留痕可查
    rec20=db.scalar(select(CumulativeRecord).where(CumulativeRecord.month==month,CumulativeRecord.channel=='直营内容',CumulativeRecord.day=='2026-10-20'))
    bad=[{'day':'2026-10-20','channel':'直营内容','gross':round(rec20.gross-5000.0,2),'refunds':rec20.refunds,'discount':rec20.discount,'recognized_net':rec20.recognized_net,'visits':rec20.visits}]
    rejected=ledger_svc.ingest(db,month,bad,'seed-ledger-regression',admin)
    assert rejected.status=='rejected'
    # 2026-11 月中账期：合作渠道缺 9、10 两日报数，9–11 日保留待补，差额不摊到单日；暂不可发布
    month2='2026-11'
    ledger_svc.ensure_month(db,month2)
    daily2=_daily_values(rng,range(1,13))
    skip={('合作渠道',9),('合作渠道',10)}
    ledger_svc.ingest(db,month2,_cumulative_rows(month2,daily2,skip),'seed-ledger-202611',admin)
    db.add(Audit(actor='seed',action='demo.ledger',detail={'months':[month,month2],'published_batch':o2.batch_no},at=time.time()))
def seed():
    migrate()
    with Session() as db:
        for role,name in [('admin','林知 · 业务负责人'),('analyst','陈舟 · 分析员'),('viewer','周禾 · 观察员')]:
            email=role+'@demo.local'
            if not db.scalar(select(User).where(User.email==email)):
                db.add(User(email=email,name=name,role=role,password=hash_password('Demo123!')))
        db.flush()
        m=metadata()
        d=db.scalar(select(Dataset).where(Dataset.name==m['dataset_name']))
        if not d:
            rows=seed_records()
            d=Dataset(name=m['dataset_name'],source=m['short']+'-202611.csv',records=rows,checksum=checksum(rows),created_at=time.time())
            db.add(d); db.flush()
        if not db.scalar(select(Job).where(Job.name=='基线复核 · '+m['name'])):
            params={p['key']:p['default'] for p in m.get('parameters',[])}
            result=analyze(d.records,params)
            json.dumps(result,ensure_ascii=False,allow_nan=False)
            admin=db.scalar(select(User).where(User.role=='admin'))
            j=Job(name='基线复核 · '+m['name'],dataset_id=d.id,params=params,status='completed',result=result,created_by=admin.id,created_at=time.time()-3600,finished_at=time.time()-3595,approved=True)
            db.add(j);db.flush()
            r=Report(name='每日业务复核简报',job_id=j.id,destination='业务复核组 · 本地收件箱',interval_seconds=86400,next_run=time.time()+86400,enabled=True)
            db.add(r);db.flush();deliver(db,r)
            db.add(Audit(actor='seed',action='demo.baseline',detail={'dataset':d.id},at=time.time()))
        admin=db.scalar(select(User).where(User.role=='admin'))
        seed_ledger(db,admin,m)
        db.commit()
        counts={model.__tablename__:db.scalar(select(func.count()).select_from(model)) for model in [User,Dataset,Job,Report,Delivery,Audit]}
        print(json.dumps(counts,ensure_ascii=False))
        return counts
if __name__=='__main__':seed()
