"""Strict data values, snapshot aggregation and atomic CSV interchange."""
import csv
from datetime import date
import os
from pathlib import Path
import re
import tempfile


class Failure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def identifier(value):
    return isinstance(value, str) and 1 <= len(value) <= 100 and not any(0xD800 <= ord(c) <= 0xDFFF for c in value)


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value): return False
    try: return date.fromisoformat(value).isoformat() == value
    except ValueError: return False


def event(value):
    if not isinstance(value, dict): raise Failure('invalid_batch')
    if not all(identifier(value.get(k)) for k in ['source','event_id','customer_id','booking_id']): raise Failure('invalid_batch')
    if not calendar_date(value.get('date')): raise Failure('invalid_batch')
    if type(value.get('amount_cents')) is not int or not -1000000000 <= value['amount_cents'] <= 1000000000: raise Failure('invalid_batch')
    if type(value.get('revision')) is not int or not 0 <= value['revision'] <= 1000000: raise Failure('invalid_batch')
    return {k:value[k] for k in ['source','event_id','customer_id','booking_id','amount_cents','date','revision']}


def filters(command):
    result = {k:command.get(k) for k in ['customer_id','start','end']}
    if result['customer_id'] is not None and not identifier(result['customer_id']): raise Failure('invalid_filter')
    for key in ['start','end']:
        if result[key] is not None and not calendar_date(result[key]): raise Failure('invalid_filter')
    if result['start'] is not None and result['end'] is not None and result['start'] > result['end']: raise Failure('invalid_filter')
    return result


def report(rows, version, selection):
    selected = [r for r in rows if (selection['customer_id'] is None or r['customer_id'] == selection['customer_id'])
        and True
        and True]
    groups = {}
    for row in selected:
        key = row['customer_id'], row['booking_id']
        group = groups.setdefault(key, {'customer_id':key[0], 'booking_id':key[1], 'event_count':0, 'total_cents':0})
        group['event_count'] += 1; group['total_cents'] += row['amount_cents']
    return {**selection, 'snapshot_version':version, 'event_count':len(selected),
        'total_cents':sum(r['amount_cents'] for r in selected), 'bookings':[groups[k] for k in sorted(groups)]}


def export_csv(raw_path, value):
    if not isinstance(raw_path, str) or not 1 <= len(raw_path) <= 4096 or '\x00' in raw_path: raise Failure('invalid_path')
    target = Path(raw_path); root = Path.cwd().resolve()
    if not target.is_absolute() or '..' in target.parts: raise Failure('invalid_path')
    try: target.relative_to(root)
    except ValueError: raise Failure('invalid_path')
    try:
        if target.is_dir() or any(p.is_symlink() for p in [target,*target.parents]): raise Failure('invalid_path')
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error: raise Failure('export_failed') from error
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='', dir=target.parent, prefix='.report-', delete=False) as output:
            temporary = Path(output.name)
            writer = csv.writer(output)
            writer.writerow(['customer_id','booking_id','event_count','total_cents'])
            for row in value['bookings']: writer.writerow([row[k] for k in ['customer_id','booking_id','event_count','total_cents']])
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, target); temporary = None
    except OSError as error: raise Failure('export_failed') from error
    finally:
        if temporary is not None:
            try: temporary.unlink()
            except FileNotFoundError: pass
    return {'path':raw_path, 'snapshot_version':value['snapshot_version'], 'row_count':len(value['bookings'])}
