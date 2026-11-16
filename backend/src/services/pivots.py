import os,json,hashlib,glob,tempfile
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from src.models.entities import Pivot,PivotRun,PivotEvent
from src.services.analysis import checksum,validate_snapshot,validate_result

TERMINAL=('done','cancelled')
LEASE_SECONDS=int(os.getenv('PIVOT_LEASE_SECONDS','300'))
ARTIFACTS=Path(os.getenv('ARTIFACTS_DIR','/artifacts'))

def now_iso():
 return datetime.now(timezone.utc).isoformat(timespec='seconds')
def now_ms():
 return int(datetime.now(timezone.utc).timestamp()*1000)
def artifact_path(pid):
 return ARTIFACTS/(str(pid)+'.json')
def sha_file(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def remove_artifacts(pid):
 """Callers hold the pivot row lock, so no publish can interleave with a removal."""
 ARTIFACTS.mkdir(parents=True,exist_ok=True)
 for p in [artifact_path(pid),*[Path(x) for x in glob.glob(str(ARTIFACTS/f'.{pid}.*.tmp'))]]:
  try:p.unlink()
  except OSError:pass
def write_artifact(pid,payload,token):
 """Temp file + fsync + atomic rename: readers never observe a partially written file."""
 ARTIFACTS.mkdir(parents=True,exist_ok=True)
 body=json.dumps(payload,ensure_ascii=False,indent=2).encode()
 fd,tmp=tempfile.mkstemp(prefix=f'.{pid}.{token[:12]}.',suffix='.tmp',dir=str(ARTIFACTS))
 try:
  with os.fdopen(fd,'wb') as f:
   f.write(body);f.flush();os.fsync(f.fileno())
  os.replace(tmp,artifact_path(pid))
  try:
   d=os.open(str(ARTIFACTS),os.O_DIRECTORY);os.fsync(d);os.close(d)
  except OSError:pass
 except Exception:
  try:os.unlink(tmp)
  except OSError:pass
  raise
 return hashlib.sha256(body).hexdigest(),len(body)

def event(s,pid,from_state,to_state,actor='',detail='',attempt=None):
 s.add(PivotEvent(pivot_id=pid,from_state=from_state,to_state=to_state,attempt=attempt,actor=actor or '',detail=(detail or '')[:2000],created=now_iso()))
def events(s,pid):
 return [{'id':e.id,'pivot_id':e.pivot_id,'from_state':e.from_state,'to_state':e.to_state,'attempt':e.attempt,'actor':e.actor,'detail':e.detail,'created':e.created}
  for e in s.query(PivotEvent).filter_by(pivot_id=pid).order_by(PivotEvent.id).all()]
def _run(s,pid,lock=False):
 q=s.query(PivotRun).filter_by(pivot_id=pid)
 return (q.populate_existing().with_for_update().first() if lock else q.first())
def _pivot(s,pid,lock=False):
 q=s.query(Pivot).filter_by(id=pid)
 return (q.populate_existing().with_for_update().first() if lock else q.first())

def ensure_run(s,p,lock=False):
 """Every pivot owns exactly one run row, so retries never create a second task."""
 run=_run(s,p.id,lock)
 if run:return run
 snap=p.result.get('snapshot') if isinstance(p.result,dict) and isinstance(p.result.get('snapshot'),list) else None
 run=PivotRun(pivot_id=p.id,snapshot=snap,snapshot_checksum=checksum(snap) if snap is not None else None,
  lease_until=0,attempt=0,retry_count=0,queued_at=now_iso(),last_error='')
 s.add(run)
 try:s.flush()
 except IntegrityError:
  s.rollback()
  run=_run(s,p.id)
  if run:return run
  raise
 return run

def create(s,data,rows,actor):
 p=Pivot(**data.model_dump(),state='queued',result=None,error='')
 s.add(p);s.flush()
 run=PivotRun(pivot_id=p.id,snapshot=rows,snapshot_checksum=checksum(rows),lease_until=0,attempt=0,retry_count=0,queued_at=now_iso(),last_error='')
 s.add(run)
 event(s,p.id,None,'queued',actor,'冻结 %d 条场次明细，checksum %s'%(len(rows),run.snapshot_checksum),0)
 s.commit()
 return p

def mark_queue_unavailable(s,p,error):
 """The task keeps its id and frozen snapshot; retry can enqueue it again later."""
 p=_pivot(s,p.id,True)
 if not p or p.state!='queued':return
 run=_run(s,p.id,True)
 p.state='failed';p.error=error
 if run:run.last_error=error;run.claim_token=None;run.lease_until=0
 event(s,p.id,'queued','failed','system',error,run.attempt if run else None)
 s.commit()

def claim(s,pid,worker_id):
 """Atomic ownership. Duplicate deliveries, late processes and cancelled tasks lose here."""
 p=_pivot(s,pid,True)
 if not p:return None
 run=ensure_run(s,p,True)
 if p.state!='queued':return None
 if run.snapshot is None:
  p.state='failed';p.error='冻结明细缺失，无法恢复；请新建透视'
  run.last_error=p.error
  event(s,pid,'queued','failed',worker_id,p.error,run.attempt)
  s.commit()
  return None
 try:validate_snapshot(run.snapshot,run.snapshot_checksum)
 except ValueError as e:
  p.state='failed';p.error=str(e)
  run.last_error=str(e);run.claim_token=None;run.lease_until=0;run.finished_at=now_iso()
  event(s,pid,'queued','failed',worker_id,str(e),run.attempt)
  s.commit()
  return None
 token=uuid4().hex
 run.attempt=(run.attempt or 0)+1
 run.claim_token=token;run.worker_id=worker_id;run.lease_until=now_ms()+LEASE_SECONDS*1000
 run.started_at=now_iso();run.finished_at=None;run.last_error=''
 p.state='running';p.error=''
 event(s,pid,'queued','running',worker_id,'第 %d 次执行，租约 %d 秒'%(run.attempt,LEASE_SECONDS),run.attempt)
 remove_artifacts(pid)
 s.commit()
 return {'pivot_id':pid,'token':token,'attempt':run.attempt,'snapshot':run.snapshot,'snapshot_checksum':run.snapshot_checksum,'row_dim':p.row_dim,'col_dim':p.col_dim}

def _owns(p,run,task):
 return bool(p and run and p.state=='running' and run.claim_token==task['token'] and run.attempt==task['attempt'])

def renew(s,task):
 """Extend the lease only while this attempt still owns the pivot, so recovery can tell live from dead."""
 p=_pivot(s,task['pivot_id'],True)
 run=_run(s,task['pivot_id'],True)
 if not _owns(p,run,task):return False
 run.lease_until=now_ms()+LEASE_SECONDS*1000
 s.commit()
 return True

def publish(s,task,result):
 """Frozen rows -> validated conserved result -> artifact -> done, all in one transaction.
 Only the current claim holder may publish; a failed write never becomes a downloadable result."""
 pid=task['pivot_id']
 p=_pivot(s,pid,True)
 run=_run(s,pid,True)
 if not _owns(p,run,task):return False
 payload={**result,'snapshot':run.snapshot}
 try:
  validate_result(payload,run.snapshot_checksum)
  sha,size=write_artifact(pid,payload,task['token'])
 except Exception as e:
  if _owns(p,run,task):
   p.state='failed';p.error=str(e) or '结果落盘失败'
   run.last_error=p.error;run.claim_token=None;run.lease_until=0;run.finished_at=now_iso()
   event(s,pid,'running','failed',run.worker_id or 'worker',p.error,run.attempt)
   remove_artifacts(pid)
  s.commit()
  raise
 p.state='done';p.result=payload;p.error=''
 run.published_at=now_iso();run.finished_at=now_iso();run.claim_token=None;run.lease_until=0
 run.artifact_sha256=sha;run.artifact_size=size;run.last_error=''
 event(s,pid,'running','done',run.worker_id or 'worker','结果入库并落盘，sha256 %s'%sha,run.attempt)
 s.commit()
 return True

def fail(s,task,error):
 pid=task['pivot_id']
 p=_pivot(s,pid,True)
 run=_run(s,pid,True)
 if not _owns(p,run,task):return False
 p.state='failed';p.error=error or '透视计算失败'
 run.last_error=p.error;run.claim_token=None;run.lease_until=0;run.finished_at=now_iso()
 event(s,pid,'running','failed',run.worker_id or 'worker',p.error,run.attempt)
 remove_artifacts(pid)
 s.commit()
 return True

def _stale(run,alive):
 """A run is dead when it holds no claim, its lease expired, or its worker no longer heartbeats."""
 if not run.claim_token:return True
 if (run.lease_until or 0)<now_ms():return True
 return bool(alive and not alive(run.worker_id))

def recover(s,worker_id,alive=None,repair_artifacts=True):
 """Requeue work left by a crashed or replaced process. Keeps the pivot id and frozen snapshot,
 never creates another task, and only steals work whose owner is provably gone.
 Artifact repair is optional because it validates every published result; the on-demand gate
 in ready_result() still rebuilds a missing file at download time."""
 ids=[]
 for pid in [x.id for x in s.query(Pivot).filter(Pivot.state.in_(['queued','running'])).order_by(Pivot.id).all()]:
  p=_pivot(s,pid,True)
  if not p:continue
  run=ensure_run(s,p,True)
  if p.state=='queued':
   if run.snapshot is None:
    p.state='failed';p.error='冻结明细缺失，无法恢复；请新建透视'
    run.last_error=p.error
    event(s,pid,'queued','failed',worker_id,p.error,run.attempt)
   else:
    run.claim_token=None;run.lease_until=0
    ids.append(pid)
  elif p.state=='running' and _stale(run,alive):
   run.claim_token=None;run.lease_until=0
   p.state='queued';p.error=''
   event(s,pid,'running','queued',worker_id,'执行进程中断或租约过期，按原编号与冻结明细重新排队',run.attempt)
   ids.append(pid)
  s.commit()
 if repair_artifacts:repair(s,worker_id)
 return ids

def repair(s,worker_id):
 """Recreate an artifact that vanished after a successful publish, without recomputing or changing ids."""
 for p in s.query(Pivot).filter(Pivot.state=='done').all():
  run=ensure_run(s,p)
  if not isinstance(p.result,dict):continue
  try:validate_result(p.result,run.snapshot_checksum)
  except ValueError:continue
  path=artifact_path(p.id)
  if path.exists() and run.artifact_sha256 and sha_file(path)==run.artifact_sha256:continue
  try:sha,size=write_artifact(p.id,p.result,'repair')
  except Exception:continue
  run.artifact_sha256=sha;run.artifact_size=size
  event(s,p.id,'done','done',worker_id,'结果文件缺失或校验不符，已按冻结结果重建')
  s.commit()

def retry(s,p,actor):
 p=_pivot(s,p.id,True)
 if not p:raise HTTPException(404,'透视方案不存在')
 if p.state!='failed':raise HTTPException(409,'仅计算失败的透视可以按原编号重试')
 run=ensure_run(s,p,True)
 if run.snapshot is None:raise HTTPException(409,'冻结明细缺失，无法按原编号恢复，请新建透视')
 prev=p.state
 run.retry_count=(run.retry_count or 0)+1
 run.claim_token=None;run.lease_until=0;run.finished_at=None;run.last_error=''
 run.queued_at=now_iso()
 p.state='queued';p.error=''
 event(s,p.id,'failed','queued',actor,'重试第 %d 次，沿用原编号与冻结明细（checksum %s）'%(run.retry_count,run.snapshot_checksum),run.attempt)
 remove_artifacts(p.id)
 s.commit()
 return p

def cancel(s,p,actor):
 p=_pivot(s,p.id,True)
 if not p:raise HTTPException(404,'透视方案不存在')
 if p.state in TERMINAL:raise HTTPException(409,'透视已结束，不能取消')
 run=ensure_run(s,p,True)
 prev=p.state
 p.state='cancelled';p.error=''
 run.claim_token=None;run.lease_until=0;run.finished_at=now_iso()
 event(s,p.id,prev,'cancelled',actor,'取消未发布的透视')
 remove_artifacts(p.id)
 s.commit()
 return p

def ready_result(s,p):
 """Single gate for download, drill-down and review drafting:
 done + complete conserved in-DB result + artifact on disk matching its sha256.
 Takes the pivot row lock so a concurrent cancel cannot flip the state under the caller."""
 p=_pivot(s,p.id,True) if p is not None else p
 if not p:raise HTTPException(404,'透视方案不存在')
 if p.state!='done':raise HTTPException(409,'透视未成功完成，不能下载或复核')
 run=_run(s,p.id,True)
 created=False
 if not run:run=ensure_run(s,p,True);created=True
 try:validate_result(p.result,run.snapshot_checksum)
 except ValueError as e:raise HTTPException(409,'透视结果不完整或未通过守恒校验：'+str(e))
 path=artifact_path(p.id)
 if not path.exists() or not run.artifact_sha256 or sha_file(path)!=run.artifact_sha256:
  try:sha,size=write_artifact(p.id,p.result,'repair')
  except Exception as e:raise HTTPException(503,'结果落盘失败，请稍后重试：'+str(e))
  run.artifact_sha256=sha;run.artifact_size=size
  event(s,p.id,'done','done','system','结果文件缺失或校验不符，已按冻结结果重建')
  s.commit()
 elif created:s.commit()
 return p.result

def view(s,p):
 d={c.name:getattr(p,c.name) for c in p.__table__.columns}
 # The frozen rows are large; download/drill serve them from the artifact and snapshot themselves.
 if isinstance(p.result,dict):d['result']={k:v for k,v in p.result.items() if k!='snapshot'}
 run=_run(s,p.id)
 d['attempt']=run.attempt if run else 0
 d['retry_count']=run.retry_count if run else 0
 d['queued_at']=run.queued_at if run else None
 d['started_at']=run.started_at if run else None
 d['published_at']=run.published_at if run else None
 d['finished_at']=run.finished_at if run else None
 d['worker_id']=run.worker_id if run else None
 d['snapshot_checksum']=run.snapshot_checksum if run else None
 d['has_artifact']=bool(run and run.artifact_sha256 and artifact_path(p.id).exists())
 d['can_retry']=p.state=='failed'
 d['can_cancel']=p.state not in TERMINAL
 return d
