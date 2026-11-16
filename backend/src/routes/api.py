import os
import redis
from fastapi import APIRouter,Depends,HTTPException,Response
from src.config.database import db
from src.models.entities import User,Settlement,Pivot,Review,Audit
from src.schemas.business import Login,SettlementInput,PivotInput,ReviewInput,ReviewEdit
from src.middlewares.auth import current,editor,admin
from src.utils.security import verify,token
from src.services.business import audit,dump
from src.services.settlements import save
from src.services.analysis import key
from src.services import pivots as lifecycle
from src.controllers.business import ensure_pivot,ensure_review,cell
router=APIRouter()
def queue():
 return redis.Redis.from_url(os.environ['REDIS_URL'])
@router.post('/auth/login')
def login(data:Login,s=Depends(db)):
 u=s.query(User).filter_by(email=data.email).first()
 if not u or not verify(data.password,u.password):raise HTTPException(401,'账号或密码错误')
 return {'token':token(u),'user':dump(u)}
@router.get('/me')
def me(u=Depends(current)):return dump(u)
@router.get('/settlements')
def settlements(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
@router.post('/settlements')
def create(data:SettlementInput,u=Depends(editor),s=Depends(db)):
 r=save(s,data);audit(s,u,'录入结算 '+r['code']);return r
@router.put('/settlements/{i}')
def edit(i:int,data:SettlementInput,u=Depends(editor),s=Depends(db)):
 r=save(s,data,i);audit(s,u,'修订结算 '+str(i));return r
@router.get('/pivots')
def pivots(u=Depends(current),s=Depends(db)):return [lifecycle.view(s,r) for r in s.query(Pivot).order_by(Pivot.id.desc()).all()]
@router.post('/pivots')
def submit(data:PivotInput,u=Depends(editor),s=Depends(db)):
 rows=[dump(r) for r in s.query(Settlement).order_by(Settlement.id).all()]
 if not rows:raise HTTPException(409,'没有结算记录，请先录入场次后再新建透视')
 r=lifecycle.create(s,data,rows,u.email)
 try:queue().rpush('stage:pivots',r.id)
 except redis.RedisError:
  lifecycle.mark_queue_unavailable(s,r,'队列暂不可用；任务已保留，可稍后重试原编号')
  raise HTTPException(503,'队列暂不可用，任务已保留，可稍后重试原编号')
 audit(s,u,'提交透视 '+str(r.id));return lifecycle.view(s,r)
@router.get('/pivots/{i}')
def detail(i:int,u=Depends(current),s=Depends(db)):
 return lifecycle.view(s,ensure_pivot(s,i))
@router.get('/pivots/{i}/events')
def pivot_events(i:int,u=Depends(current),s=Depends(db)):
 ensure_pivot(s,i);return lifecycle.events(s,i)
@router.post('/pivots/{i}/retry')
def retry(i:int,u=Depends(editor),s=Depends(db)):
 p=lifecycle.retry(s,ensure_pivot(s,i),u.email)
 try:queue().rpush('stage:pivots',p.id)
 except redis.RedisError:
  lifecycle.mark_queue_unavailable(s,p,'队列暂不可用；任务已保留，可稍后重试原编号')
  raise HTTPException(503,'队列暂不可用，任务已保留，可稍后重试原编号')
 audit(s,u,'重试透视 '+str(i));return lifecycle.view(s,p)
@router.post('/pivots/{i}/cancel')
def cancel(i:int,u=Depends(editor),s=Depends(db)):
 p=lifecycle.cancel(s,ensure_pivot(s,i),u.email)
 audit(s,u,'取消透视 '+str(i));return lifecycle.view(s,p)
@router.get('/pivots/{i}/drill')
def drill(i:int,row_key:str,col_key:str,u=Depends(current),s=Depends(db)):
 r,c=cell(s,i,row_key,col_key)
 return {'cell':c,'rows':[x for x in r.result['snapshot'] if key(x,r.row_dim)==row_key and key(x,r.col_dim)==col_key]}
@router.get('/pivots/{i}/export')
def export(i:int,u=Depends(current),s=Depends(db)):
 r=ensure_pivot(s,i)
 lifecycle.ready_result(s,r)
 # Serve exactly the published artifact that passed the conservation gate. Read it before the
 # response is built so a concurrent cancel can at worst return 409, never truncated JSON.
 try:body=lifecycle.artifact_path(i).read_text(encoding='utf-8')
 except FileNotFoundError:raise HTTPException(409,'透视结果文件不可用，不能下载')
 return Response(body,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="stage-pivot-{i}.json"','Cache-Control':'no-store'})
@router.get('/reviews')
def reviews(u=Depends(current),s=Depends(db)):return [dump(r) for r in s.query(Review).order_by(Review.id.desc()).all()]
@router.post('/reviews')
def review(data:ReviewInput,u=Depends(editor),s=Depends(db)):
 run,c=cell(s,data.pivot_id,data.row_key,data.col_key)
 r=Review(**data.model_dump(),book_cents=c['net_cents'],difference_cents=data.expected_cents-c['net_cents']);s.add(r);s.commit();audit(s,u,'起草差异复核 '+str(r.id));return dump(r)
@router.put('/reviews/{i}')
def edit_review(i:int,data:ReviewEdit,u=Depends(editor),s=Depends(db)):
 r=ensure_review(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核复核单不可覆盖，请新建复核')
 r.expected_cents=data.expected_cents;r.difference_cents=data.expected_cents-r.book_cents;r.note=data.note;s.commit();audit(s,u,'修改差异复核 '+str(i));return dump(r)
@router.post('/reviews/{i}/approve')
def approve(i:int,u=Depends(admin),s=Depends(db)):
 r=ensure_review(s,i)
 if r.status!='draft':raise HTTPException(409,'已签核复核单不可重复签核')
 r.status='approved';s.commit();audit(s,u,'签核差异复核 '+str(i));return dump(r)
@router.get('/audits')
def audits(u=Depends(admin),s=Depends(db)):return [dump(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
