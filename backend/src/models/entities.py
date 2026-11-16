from sqlalchemy import Column,Integer,BigInteger,String,JSON,Text,ForeignKey
from src.config.database import Base
class User(Base):
 __tablename__='users'
 id=Column(Integer,primary_key=True);email=Column(String(100),unique=True,nullable=False);password=Column(String(200));role=Column(String(20))
class Settlement(Base):
 __tablename__='settlements'
 id=Column(Integer,primary_key=True);code=Column(String(60),unique=True,nullable=False);day=Column(String(10));venue=Column(String(40));play=Column(String(60));channel=Column(String(30));gross_cents=Column(BigInteger);refund_cents=Column(BigInteger);fee_cents=Column(BigInteger);seats=Column(Integer);checked=Column(Integer)
class Pivot(Base):
 __tablename__='pivots'
 id=Column(Integer,primary_key=True);name=Column(String(100));row_dim=Column(String(30));col_dim=Column(String(30));state=Column(String(20),default='queued');result=Column(JSON,nullable=True);error=Column(Text,default='')
class PivotRun(Base):
 """Lifecycle state kept in its own table so an existing pivots table can be upgraded by create_all()."""
 __tablename__='pivot_runs'
 pivot_id=Column(Integer,ForeignKey('pivots.id'),primary_key=True)
 snapshot=Column(JSON,nullable=True)
 snapshot_checksum=Column(String(64),nullable=True)
 claim_token=Column(String(64),nullable=True)
 worker_id=Column(String(100),nullable=True)
 lease_until=Column(BigInteger,default=0,nullable=False)
 attempt=Column(Integer,default=0,nullable=False)
 retry_count=Column(Integer,default=0,nullable=False)
 queued_at=Column(String(40),nullable=True)
 started_at=Column(String(40),nullable=True)
 published_at=Column(String(40),nullable=True)
 finished_at=Column(String(40),nullable=True)
 artifact_sha256=Column(String(64),nullable=True)
 artifact_size=Column(BigInteger,nullable=True)
 last_error=Column(Text,default='')
class PivotEvent(Base):
 __tablename__='pivot_events'
 id=Column(Integer,primary_key=True)
 pivot_id=Column(Integer,ForeignKey('pivots.id'),index=True,nullable=False)
 from_state=Column(String(20),nullable=True)
 to_state=Column(String(20),nullable=False)
 attempt=Column(Integer,nullable=True)
 actor=Column(String(100))
 detail=Column(Text,default='')
 created=Column(String(40))
class Review(Base):
 __tablename__='reviews'
 id=Column(Integer,primary_key=True);pivot_id=Column(Integer,ForeignKey('pivots.id'));row_key=Column(String(100));col_key=Column(String(100));book_cents=Column(BigInteger);expected_cents=Column(BigInteger);difference_cents=Column(BigInteger);note=Column(Text);status=Column(String(20),default='draft')
class Audit(Base):
 __tablename__='audits'
 id=Column(Integer,primary_key=True);actor=Column(String(100));action=Column(String(200));created=Column(String(40))
