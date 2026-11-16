from fastapi import HTTPException
from src.models.entities import Pivot,Review
from src.services.analysis import key
from src.services import pivots as lifecycle
def ensure_pivot(s,i):
 r=s.get(Pivot,i)
 if not r:raise HTTPException(404,'透视方案不存在')
 return r
def ensure_review(s,i):
 r=s.get(Review,i)
 if not r:raise HTTPException(404,'差异复核不存在')
 return r
def cell(s,i,a,b):
 r=ensure_pivot(s,i)
 # 下钻/起草复核 only open on a published, conserved, on-disk result.
 result=lifecycle.ready_result(s,r)
 c=next((c for c in result['cells'] if c['row_key']==a and c['col_key']==b),None)
 if not c or c['count']==0:raise HTTPException(404,'该透视单元没有结算记录')
 return r,c
