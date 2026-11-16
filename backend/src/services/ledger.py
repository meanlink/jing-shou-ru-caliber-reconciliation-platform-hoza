"""累计来账接入、日账差分、缺日待补与月结发布。

渠道报来的是月内累计数：月初以零为起点，相邻两日累计相减生成日账；
缺日不摊跨日差额，保留待补；累计回退整批拒收；发布前核对日账合计等于月末累计，
核对通过在单事务内建账并一次性切换可分析批次。
"""
import time, math
from calendar import monthrange
from datetime import date, timedelta
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from src.models import Dataset, IngestBatch, CumulativeRecord, DailyAccount, MonthState, PublishOrder
from src.utils.serialization import checksum

METRICS = ['gross', 'refunds', 'discount', 'recognized_net', 'visits']
MONEY = ['gross', 'refunds', 'discount', 'recognized_net']
MAX_VALUE = 1_000_000_000
MONEY_TOLERANCE = 0.01
EPS = 1e-6

def _parse_month(month):
    if not isinstance(month, str) or len(month) != 7 or month[4] != '-':
        raise HTTPException(422, '账期格式须为 YYYY-MM')
    try:
        year, mon = int(month[:4]), int(month[5:])
        if not 1 <= mon <= 12: raise ValueError()
    except ValueError:
        raise HTTPException(422, '账期格式须为有效 YYYY-MM')
    return year, mon

def _parse_day(raw, month, index):
    try:
        day = date.fromisoformat(str(raw))
    except (TypeError, ValueError):
        raise HTTPException(422, f'第 {index} 条日期 {raw} 不是有效日期')
    if str(day)[:7] != month:
        raise HTTPException(422, f'第 {index} 条日期 {day} 不属于账期 {month}')
    return day

def ensure_month(db, month):
    """保证账期锁行存在；独立小事务提交，供后续 SELECT FOR UPDATE 使用。"""
    _parse_month(month)
    if not db.get(MonthState, month):
        db.add(MonthState(month=month, current_dataset_id=None, updated_at=time.time()))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()

def lock_month(db, month):
    """接账与发布共用同一把账期锁，并发时各自看到完整的已提交版本。"""
    return db.scalar(select(MonthState).where(MonthState.month == month).with_for_update())

def _validate_record(raw, month, index):
    if not isinstance(raw, dict):
        raise HTTPException(422, f'第 {index} 条记录不是 JSON 对象')
    channel = str(raw.get('channel', '')).strip()
    if not channel or len(channel) > 80:
        raise HTTPException(422, f'第 {index} 条渠道为空或超过 80 字')
    day = _parse_day(raw.get('day'), month, index)
    values = {}
    for key in METRICS:
        value = raw.get(key)
        try:
            if isinstance(value, bool) or not math.isfinite(float(value)): raise ValueError()
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(422, f'第 {index} 条 {key} 必须为有限数值')
        if not 0 <= value <= MAX_VALUE:
            raise HTTPException(422, f'第 {index} 条 {key} 超出 0 至 10 亿范围')
        values[key] = value
    if not values['visits'].is_integer():
        raise HTTPException(422, f'第 {index} 条累计访问数必须为整数')
    values['visits'] = int(values['visits'])
    return channel, day, values

def _reject(db, month, source, rows, errors, user):
    batch = IngestBatch(month=month, source=source, rows=rows, status='rejected', errors=errors[:200], effects=[], created_by=user.id, created_at=time.time())
    db.add(batch); db.flush()
    return batch

def ingest(db, month, records, source, user):
    """接入一批累计来账（含迟到记录与更正）。累计回退或自然键重复时整批拒收，不留半批。"""
    _parse_month(month)
    if not 1 <= len(records) <= 500:
        raise HTTPException(422, '单次接账 1 至 500 条记录')
    parsed, seen, duplicates = [], set(), []
    for index, raw in enumerate(records, 1):
        channel, day, values = _validate_record(raw, month, index)
        key = (channel, str(day))
        if key in seen:
            duplicates.append({'reason': 'natural_key_duplicate', 'channel': channel, 'day': str(day), 'detail': f'同批次内 {channel} {day} 重复出现'})
        seen.add(key)
        parsed.append((channel, day, values))
    if duplicates:
        return _reject(db, month, source, len(records), duplicates, user)
    lock_month(db, month)
    channels = sorted({channel for channel, _, _ in parsed})
    stored = {(r.channel, r.day): r for r in db.scalars(select(CumulativeRecord).where(CumulativeRecord.month == month, CumulativeRecord.channel.in_(channels)))}
    errors = []
    for channel, day, values in parsed:
        rec = stored.get((channel, str(day)))
        if rec:
            for key in METRICS:
                if values[key] < getattr(rec, key) - EPS:
                    errors.append({'reason': 'cumulative_regression', 'channel': channel, 'day': str(day), 'field': key,
                                   'detail': f'{channel} {day} 更正后累计 {key}={values[key]} 低于已入账值 {getattr(rec, key)}，累计不得回退'})
    merged = {}
    for (channel, day), rec in stored.items():
        merged.setdefault(channel, {})[day] = {key: getattr(rec, key) for key in METRICS}
    for channel, day, values in parsed:
        merged.setdefault(channel, {})[str(day)] = values
    for channel, series in merged.items():
        ordered = sorted(series)
        for prev, cur in zip(ordered, ordered[1:]):
            for key in METRICS:
                if series[cur][key] < series[prev][key] - EPS:
                    errors.append({'reason': 'cumulative_regression', 'channel': channel, 'day': cur, 'field': key,
                                   'detail': f'{channel} 入账后 {cur} 累计 {key}={series[cur][key]} 低于 {prev} 的 {series[prev][key]}，累计序列不得倒退'})
    if errors:
        return _reject(db, month, source, len(records), errors, user)
    batch = IngestBatch(month=month, source=source, rows=len(records), status='accepted', errors=[], effects=[], created_by=user.id, created_at=time.time())
    db.add(batch); db.flush()
    now = time.time()
    for channel, day, values in parsed:
        rec = stored.get((channel, str(day)))
        if rec:
            for key in METRICS: setattr(rec, key, values[key])
            rec.batch_id = batch.id; rec.received_at = now
        else:
            rec = CumulativeRecord(month=month, channel=channel, day=str(day), batch_id=batch.id, received_at=now, **values)
            db.add(rec); stored[(channel, str(day))] = rec
    db.flush()
    effects = []
    for channel in channels:
        effects.extend(rederive(db, month, channel))
    batch.effects = effects[:500]
    return batch

def rederive(db, month, channel):
    """由累计来账重算某渠道整月日账：月初以零为起点，相邻累计相减；跨日缺口整段记待补。

    迟到记录或更正会改变相邻两日日账，返回值即这些差分效果，供接账批次留痕与页面追查。
    """
    records = sorted(db.scalars(select(CumulativeRecord).where(CumulativeRecord.month == month, CumulativeRecord.channel == channel)), key=lambda r: r.day)
    existing = {r.day: r for r in db.scalars(select(DailyAccount).where(DailyAccount.month == month, DailyAccount.channel == channel))}
    year, mon = _parse_month(month)
    prev_day = date(year, mon, 1) - timedelta(days=1)  # 月初以零为起点
    prev_values = {key: 0 for key in METRICS}
    prev_record_id = None
    now, seen, rebuilt = time.time(), set(), []
    for rec in records:
        current = date.fromisoformat(rec.day)
        values = {key: getattr(rec, key) for key in METRICS}
        if (current - prev_day).days == 1:
            daily = {key: round(values[key] - prev_values[key], 4) for key in MONEY}
            daily['visits'] = int(values['visits'] - prev_values['visits'])
            rebuilt.append((rec.day, 'derived', daily, {'kind': 'diff', 'prev_day': str(prev_day), 'prev_record_id': prev_record_id, 'record_id': rec.id}))
        else:
            # 缺日：跨日差额记入缺口待补，不摊到任何一天
            unallocated = {key: round(values[key] - prev_values[key], 4) for key in METRICS}
            day = prev_day + timedelta(days=1)
            while day <= current:
                rebuilt.append((str(day), 'pending', {key: None for key in METRICS},
                                {'kind': 'gap', 'gap_from': str(prev_day), 'gap_to': rec.day, 'unallocated': unallocated}))
                day += timedelta(days=1)
        prev_day, prev_values, prev_record_id = current, values, rec.id
    effects = []
    for day, status, values, trace in rebuilt:
        seen.add(day)
        old = existing.get(day)
        if old:
            changed = {key: [getattr(old, key), values[key]] for key in METRICS if getattr(old, key) != values[key]}
            trace_changed = (old.trace or {}) != trace
            if old.status != status or changed or trace_changed:
                entry = {'channel': channel, 'day': day, 'change': 'updated', 'status': [old.status, status], 'fields': changed}
                if trace_changed and not changed and old.status == status:
                    entry['note'] = '缺口边界或未摊差额变化'
                effects.append(entry)
            for key in METRICS: setattr(old, key, values[key])
            old.status, old.trace, old.updated_at = status, trace, now
        else:
            db.add(DailyAccount(month=month, channel=channel, day=day, status=status, trace=trace, updated_at=now, **values))
            effects.append({'channel': channel, 'day': day, 'change': 'new', 'status': [None, status], 'fields': {}})
    for day, row in existing.items():
        if day not in seen:
            db.delete(row)
    return effects

def verify_month(db, month):
    """发布前核对：每个渠道日账合计必须等于月末（最新）累计，且无缺日待补。"""
    year, mon = _parse_month(month)
    first = date(year, mon, 1)
    checks = {'month': month, 'month_end': str(date(year, mon, monthrange(year, mon)[1])), 'channels': [], 'ok': False}
    channels = [row[0] for row in db.execute(select(CumulativeRecord.channel).where(CumulativeRecord.month == month).distinct())]
    for channel in sorted(channels):
        records = sorted(db.scalars(select(CumulativeRecord).where(CumulativeRecord.month == month, CumulativeRecord.channel == channel)), key=lambda r: r.day)
        latest = records[-1]
        daily = {r.day: r for r in db.scalars(select(DailyAccount).where(DailyAccount.month == month, DailyAccount.channel == channel))}
        last = date.fromisoformat(latest.day)
        pending, sums, day = [], {key: 0 for key in METRICS}, first
        while day <= last:
            row = daily.get(str(day))
            if not row or row.status != 'derived':
                pending.append(str(day))
            else:
                for key in METRICS: sums[key] += getattr(row, key)
            day += timedelta(days=1)
        problems, metrics = [], {}
        if pending:
            problems.append(f'缺日待补 {len(pending)} 天：' + '、'.join(pending[:5]) + ('…' if len(pending) > 5 else ''))
        for key in METRICS:
            target = getattr(latest, key)
            diff = round(sums[key] - target, 4)
            ok = sums[key] == target if key == 'visits' else abs(diff) <= MONEY_TOLERANCE
            if not ok:
                problems.append(f'{key} 日账合计 {round(sums[key], 4)} 与月末累计 {target} 相差 {diff}')
            metrics[key] = {'daily_sum': round(sums[key], 4), 'cumulative': target, 'diff': diff, 'ok': ok}
        checks['channels'].append({'channel': channel, 'latest_day': latest.day, 'derived_days': (last - first).days + 1 - len(pending), 'pending_days': pending, 'metrics': metrics, 'ok': not problems, 'problems': problems})
    checks['ok'] = bool(checks['channels']) and all(c['ok'] for c in checks['channels'])
    return checks

def create_publish_order(db, month, user):
    """开立发布单：批次号按账期递增，中断后恢复同一发布单，重试沿用批次编号。"""
    _parse_month(month)
    lock_month(db, month)
    last = db.scalar(select(PublishOrder.batch_no).where(PublishOrder.month == month).order_by(PublishOrder.batch_no.desc()).limit(1))
    order = PublishOrder(month=month, batch_no=(last or 0) + 1, status='draft', created_by=user.id, created_at=time.time())
    db.add(order); db.flush()
    return order

def publish(db, order):
    """执行发布：核对通过后在同一事务内建账并切换可分析批次；重复发布幂等，不重复建账。"""
    if order.status == 'published':
        return order
    lock_month(db, order.month)
    checks = verify_month(db, order.month)
    order.checks = checks
    if not checks['ok']:
        problems = [p for c in checks['channels'] for p in c['problems']]
        order.status = 'failed'
        order.error = ('；'.join(problems) or '账期内没有累计来账，无法发布')[:950]
        return order
    daily = [r for r in db.scalars(select(DailyAccount).where(DailyAccount.month == order.month)) if r.status == 'derived']
    daily.sort(key=lambda r: (r.day, r.channel))
    records = [{'day': r.day, 'channel': r.channel, 'currency': 'CNY', 'gross': r.gross, 'refunds': r.refunds,
                'discount': r.discount, 'recognized_net': r.recognized_net, 'visits': r.visits} for r in daily]
    dataset = Dataset(name=f'累计日账 {order.month} · 第{order.batch_no}批次', source=f'ledger-publish:{order.month}#v{order.batch_no}',
                      records=records, checksum=checksum(records), created_at=time.time(), kind='published',
                      month=order.month, batch_no=order.batch_no, publish_order_id=order.id, superseded=False)
    db.add(dataset); db.flush()
    state = db.get(MonthState, order.month)
    if state.current_dataset_id:
        old = db.get(Dataset, state.current_dataset_id)
        if old: old.superseded = True  # 旧试算随之失效；已批准资料保留原值不动
    state.current_dataset_id = dataset.id
    state.updated_at = time.time()
    order.dataset_id, order.status, order.error, order.published_at = dataset.id, 'published', '', time.time()
    return order

def months_list(db):
    months = {row[0] for row in db.execute(select(CumulativeRecord.month).distinct())}
    months |= {row[0] for row in db.execute(select(PublishOrder.month).distinct())}
    months |= {row[0] for row in db.execute(select(MonthState.month))}
    out = []
    for month in sorted(months, reverse=True):
        statuses = list(db.scalars(select(DailyAccount.status).where(DailyAccount.month == month)))
        state = db.get(MonthState, month)
        out.append({'month': month, 'derived': sum(1 for s in statuses if s == 'derived'), 'pending': sum(1 for s in statuses if s == 'pending'),
                    'current_dataset_id': state.current_dataset_id if state else None,
                    'published_batches': len(list(db.scalars(select(PublishOrder.id).where(PublishOrder.month == month, PublishOrder.status == 'published'))))})
    return out

def month_detail(db, month):
    year, mon = _parse_month(month)
    state = db.get(MonthState, month)
    daily = sorted(db.scalars(select(DailyAccount).where(DailyAccount.month == month)), key=lambda r: (r.day, r.channel))
    gaps = {}
    for row in daily:
        if row.status != 'pending': continue
        trace = row.trace or {}
        key = (row.channel, trace.get('gap_from'), trace.get('gap_to'))
        gap = gaps.setdefault(key, {'channel': row.channel, 'gap_from': trace.get('gap_from'), 'gap_to': trace.get('gap_to'), 'days': [], 'unallocated': trace.get('unallocated', {})})
        gap['days'].append(row.day)
    current = db.get(Dataset, state.current_dataset_id) if state and state.current_dataset_id else None
    return {
        'month': month, 'month_end': str(date(year, mon, monthrange(year, mon)[1])),
        'current_dataset': {'id': current.id, 'name': current.name, 'batch_no': current.batch_no} if current else None,
        'checks': verify_month(db, month),
        'daily': [{'id': r.id, 'day': r.day, 'channel': r.channel, 'status': r.status, 'trace': r.trace,
                   'gross': r.gross, 'refunds': r.refunds, 'discount': r.discount, 'recognized_net': r.recognized_net, 'visits': r.visits} for r in daily],
        'gaps': sorted(gaps.values(), key=lambda g: (g['channel'], g['gap_from'] or '')),
        'ingests': [{'id': b.id, 'source': b.source, 'rows': b.rows, 'status': b.status, 'errors': b.errors, 'effects': b.effects, 'created_at': b.created_at}
                    for b in db.scalars(select(IngestBatch).where(IngestBatch.month == month).order_by(IngestBatch.id.desc()).limit(20))],
        'publish_orders': [{'id': o.id, 'batch_no': o.batch_no, 'status': o.status, 'error': o.error, 'dataset_id': o.dataset_id,
                            'checks': o.checks, 'created_at': o.created_at, 'published_at': o.published_at}
                           for o in db.scalars(select(PublishOrder).where(PublishOrder.month == month).order_by(PublishOrder.id.desc()))],
    }
