import os,time,logging,signal,socket,threading
from uuid import uuid4
from pathlib import Path
import redis
from src.config.database import Session
from src.services.analysis import pivot
from src.services import pivots as lifecycle

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
QUEUE='stage:pivots'
WORKER_ID=f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
HEARTBEAT_KEY='stage:worker:'+WORKER_ID
HEARTBEAT_TTL=15
q=redis.Redis.from_url(os.environ['REDIS_URL'])
stop=threading.Event()

def beat():
 Path('/tmp/heartbeat').touch()
 try:q.set(HEARTBEAT_KEY,1,ex=HEARTBEAT_TTL)
 except redis.RedisError:logging.exception('heartbeat key')

def beat_forever():
 while not stop.is_set():
  try:beat()
  except Exception:logging.exception('heartbeat')
  stop.wait(3)

def alive(worker_id):
 """Only a worker still publishing its heartbeat may own unfinished work."""
 try:return bool(q.exists('stage:worker:'+worker_id))
 except redis.RedisError:return True

def enqueue(ids):
 for pid in ids:
  try:q.rpush(QUEUE,pid)
  except redis.RedisError:logging.exception('requeue %s failed',pid)

def recover(repair_artifacts=True):
 """At-least-once: re-enqueue recoverable pivots that are missing from the Redis list.
 Duplicate deliveries are harmless because claim() grants ownership to exactly one attempt."""
 try:
  with Session() as s:ids=lifecycle.recover(s,WORKER_ID,alive=alive,repair_artifacts=repair_artifacts)
  pending=set()
  try:pending={int(x) for x in q.lrange(QUEUE,0,-1)}
  except redis.RedisError:pass
  missing=[pid for pid in ids if pid not in pending]
  if missing:logging.info('recovered pivots %s',missing);enqueue(missing)
 except Exception:logging.exception('recover')

def keep_alive(task,done):
 """Renew the lease while computing, so recovery only steals genuinely dead work."""
 while not stop.is_set() and not done.wait(max(5,lifecycle.LEASE_SECONDS//5)):
  try:
   with Session() as s:
    if not lifecycle.renew(s,task):return
  except Exception:logging.exception('lease renew')

def process(pid):
 with Session() as s:
  task=lifecycle.claim(s,pid,WORKER_ID)
 if not task:return
 logging.info('pivot %s attempt %s claimed by %s',pid,task['attempt'],WORKER_ID)
 beat()
 done=threading.Event()
 threading.Thread(target=keep_alive,args=(task,done),daemon=True).start()
 try:
  result=pivot(task['snapshot'],task['row_dim'],task['col_dim'])
 except Exception as e:
  logging.exception('pivot %s failed',pid)
  with Session() as s:lifecycle.fail(s,task,str(e) or '计算失败')
  return
 finally:done.set()
 try:
  with Session() as s:
   published=lifecycle.publish(s,task,result)
  if not published:logging.warning('pivot %s lost ownership before publish; discarded',pid)
  else:logging.info('pivot %s published attempt %s',pid,task['attempt'])
 except Exception as e:
  logging.exception('pivot %s publish failed',pid)
  try:
   with Session() as s:lifecycle.fail(s,task,str(e))
  except Exception:logging.exception('pivot %s fail-record failed',pid)

def main():
 beat()
 recover()
 last=time.monotonic();last_repair=last
 while not stop.is_set():
  beat()
  try:
   item=q.blpop(QUEUE,timeout=3)
  except redis.RedisError:
   logging.exception('queue unavailable');stop.wait(2);item=None
  if item:process(int(item[1]))
  now=time.monotonic()
  if now-last>30:
   # Requeue stale work; full artifact repair only every five minutes or at startup.
   do_repair=now-last_repair>300
   recover(repair_artifacts=do_repair)
   if do_repair:last_repair=now
   last=now

def shutdown(*_):
 stop.set()
 try:q.delete(HEARTBEAT_KEY)
 except redis.RedisError:pass

if __name__=='__main__':
 signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
 threading.Thread(target=beat_forever,daemon=True).start()
 try:main()
 finally:stop.set()
