import json,hashlib
DIMENSIONS={'venue','play','channel','month'}
SUMS=('gross_cents','refund_cents','fee_cents','seats','checked')
CONSERVED_KEYS=(*SUMS,'net_cents','count')
def key(row,dim):return row['day'][:7] if dim=='month' else row[dim]
def aggregate(rows):
 out={k:sum(r[k] for r in rows) for k in SUMS};out['count']=len(rows)
 out['net_cents']=out['gross_cents']-out['refund_cents']-out['fee_cents']
 out['occupancy']=out['checked']/out['seats'] if out['seats'] else None
 return out
def checksum(rows):
 return hashlib.sha256(json.dumps(rows,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def validate_snapshot(rows,expected_checksum=None):
 if not isinstance(rows,list):raise ValueError('冻结明细格式无效')
 if not rows:raise ValueError('没有结算记录，请先录入场次')
 if not all(isinstance(r,dict) for r in rows):raise ValueError('冻结明细格式无效')
 codes={r.get('code') for r in rows}
 if len(codes)!=len(rows) or None in codes:raise ValueError('场次编号重复，无法保证结算守恒')
 for r in rows:
  if not r.get('day') or len(r['day'])<7:raise ValueError('冻结明细缺少业务日期，请重新创建透视')
  if not r.get('venue') or not r.get('play') or not r.get('channel'):raise ValueError('冻结明细缺少场馆、演出或渠道')
  if any(not isinstance(r.get(k),int) for k in SUMS):raise ValueError('冻结明细金额或人数格式无效')
  if r['gross_cents']<0 or r['refund_cents']<0 or r['fee_cents']<0 or r['seats']<0 or r['checked']<0:raise ValueError('冻结明细存在负数金额或人数')
  if r['refund_cents']+r['fee_cents']>r['gross_cents']:raise ValueError('冻结明细退款与渠道费超过票款')
  if r['checked']>r['seats']:raise ValueError('冻结明细核验人数超过座位数')
 if expected_checksum and checksum(rows)!=expected_checksum:raise ValueError('冻结明细校验和不一致，快照可能已损坏')
 return rows
def pivot(rows,row_dim,col_dim):
 if row_dim not in DIMENSIONS or col_dim not in DIMENSIONS or row_dim==col_dim:raise ValueError('请选择两个不同的白名单维度')
 validate_snapshot(rows)
 row_keys=sorted({key(r,row_dim) for r in rows});col_keys=sorted({key(r,col_dim) for r in rows})
 cells=[{'row_key':a,'col_key':b,**aggregate([r for r in rows if key(r,row_dim)==a and key(r,col_dim)==b])} for a in row_keys for b in col_keys]
 row_totals=[{'key':a,**aggregate([r for r in rows if key(r,row_dim)==a])} for a in row_keys]
 col_totals=[{'key':b,**aggregate([r for r in rows if key(r,col_dim)==b])} for b in col_keys]
 total=aggregate(rows)
 conserved=all(sum(x[k] for x in cells)==sum(x[k] for x in row_totals)==sum(x[k] for x in col_totals)==total[k] for k in (*SUMS,'net_cents','count'))
 if not conserved:raise ValueError('行列总计不守恒，请核对输入')
 # 上座率必须以总核验/总座位加权计算，不能平均各场百分比。
 if total['occupancy'] is not None and not (0<=total['occupancy']<=1):raise ValueError('加权上座率超出有效范围')
 return dict(row_keys=row_keys,col_keys=col_keys,cells=cells,row_totals=row_totals,col_totals=col_totals,total=total,conserved=conserved,checksum=checksum(rows),method='金额以整数分求和；净结算=票款−退款−渠道费。上座率=总核验人数/总座位，零座位显示未定义；不平均各场百分比。每条为独立场次，渠道是主售票渠道，不拆分同场座位。月份按业务日期YYYY-MM；下钻始终读取冻结快照。')
def validate_result(result,expected_checksum=None):
 """Only a complete, conserved result may back an artifact, export or review."""
 if not isinstance(result,dict):raise ValueError('透视结果不完整')
 try:
  return _validate_result(result,expected_checksum)
 except (KeyError,TypeError,AttributeError) as e:
  raise ValueError('透视结果字段不完整') from e
def _validate_result(result,expected_checksum=None):
 rows=result.get('snapshot')
 validate_snapshot(rows,expected_checksum)
 for k in ('row_keys','col_keys','cells','row_totals','col_totals','total','conserved'):
  if k not in result:raise ValueError('透视结果字段不完整')
 if result.get('conserved') is not True:raise ValueError('透视结果未通过守恒校验')
 if result.get('checksum')!=checksum(rows):raise ValueError('透视结果与冻结明细校验和不一致')
 total=result['total']
 expected=aggregate(rows)
 if not isinstance(total,dict) or not isinstance(result['cells'],list):raise ValueError('透视结果字段不完整')
 for k in (*SUMS,'net_cents','count'):
  if k not in total or total[k]!=expected[k]:raise ValueError('透视总计与冻结明细不一致')
 if total.get('occupancy')!=expected['occupancy']:raise ValueError('透视加权上座率与冻结明细不一致')
 for k in CONSERVED_KEYS:
  if sum(x[k] for x in result['cells'])!=sum(x[k] for x in result['row_totals']):raise ValueError('透视列合计不守恒')
  if sum(x[k] for x in result['row_totals'])!=sum(x[k] for x in result['col_totals']):raise ValueError('透视行合计不守恒')
  if sum(x[k] for x in result['col_totals'])!=total[k]:raise ValueError('透视总计不守恒')
 if sum(x['count'] for x in result['cells'])!=total['count']:raise ValueError('透视场次计数不守恒')
 return result
