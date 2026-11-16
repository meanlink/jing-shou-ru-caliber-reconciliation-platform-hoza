from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from src.config.database import get_db
from src.models import PublishOrder
from src.schemas.ledger import IngestInput
from src.middlewares.auth import current_user, can_write
from src.services import ledger
from src.services.audit import record
from src.utils.serialization import ingest_dict, publish_dict
router=APIRouter(prefix='/ledger')
@router.get('/months')
def months(db=Depends(get_db),u=Depends(current_user)):
    return ledger.months_list(db)
@router.get('/months/{month}')
def detail(month:str,db=Depends(get_db),u=Depends(current_user)):
    return ledger.month_detail(db,month)
@router.post('/months/{month}/ingest',status_code=201)
def ingest(month:str,data:IngestInput,db=Depends(get_db),u=Depends(can_write)):
    ledger.ensure_month(db,month)
    batch=ledger.ingest(db,month,data.records,data.source,u)
    record(db,u.email,'ledger.ingest',{'id':batch.id,'month':month,'rows':batch.rows,'status':batch.status})
    db.commit(); return ingest_dict(batch)
@router.post('/months/{month}/publish-orders',status_code=201)
def create_order(month:str,db=Depends(get_db),u=Depends(can_write)):
    ledger.ensure_month(db,month)
    order=ledger.create_publish_order(db,month,u)
    record(db,u.email,'ledger.publish_order.create',{'id':order.id,'month':month,'batch_no':order.batch_no})
    db.commit(); return publish_dict(order)
@router.post('/publish-orders/{id}/publish')
def publish_order(id:int,db=Depends(get_db),u=Depends(can_write)):
    order=db.get(PublishOrder,id)
    if not order: raise HTTPException(404,'发布单不存在')
    ledger.ensure_month(db,order.month)
    order=db.scalar(select(PublishOrder).where(PublishOrder.id==id).with_for_update())
    order=ledger.publish(db,order)
    record(db,u.email,'ledger.publish',{'id':order.id,'month':order.month,'batch_no':order.batch_no,'status':order.status})
    db.commit(); return publish_dict(order)
