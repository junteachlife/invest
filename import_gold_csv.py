#!/usr/bin/env python3
"""Import verified Dukascopy XAU/USD OHLC CSV into existing monthly 15m replay JSON.

Expected UTC OHLC at 1m/5m/15m spacing. Avoid tick-level exports.
Usage: python import_gold_csv.py imports/xauusd/2025-01.csv --month 2025-01
"""
import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'xauusd'
TIME_FORMATS = (
    '%d.%m.%Y %H:%M:%S.%f', '%d.%m.%Y %H:%M:%S',
    '%Y.%m.%d %H:%M:%S.%f', '%Y.%m.%d %H:%M:%S',
    '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z',
    '%Y-%m-%dT%H:%M:%S.%f', '%Y-%m-%dT%H:%M:%S',
    '%Y-%m-%d %H:%M', '%d.%m.%Y %H:%M',
)

def timestamp_ms(value):
    v = str(value).strip().replace('Z', '+00:00')
    if re.fullmatch(r'\d{10,16}(\.\d+)?', v):
        n = float(v)
        return int(n * 1000 if n < 1e11 else n)
    for fmt in TIME_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    raise ValueError(f'Unsupported date/time: {value!r}')

def field(row, names):
    for key, value in row.items():
        normalized = re.sub(r'[^a-z0-9]', '', str(key).lower().lstrip('\ufeff'))
        if normalized in names:
            return value
    return None

def read_rows(csv_file):
    with csv_file.open('r', encoding='utf-8-sig', newline='') as stream:
        sample = stream.read(4096)
        stream.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
        reader = csv.DictReader(stream, dialect=dialect)
        if not reader.fieldnames:
            raise ValueError('CSV header is missing')
        found = []
        for line_no, row in enumerate(reader, 2):
            try:
                dt = field(row, {'timestamp', 'gmttime', 'datetime', 'dateandtime', 'timeutc'})
                if dt is None:
                    d = field(row, {'date'})
                    t = field(row, {'time'})
                    dt = f'{d} {t}' if d and t else d
                if dt is None:
                    raise ValueError('Missing timestamp, GMT Time, or Date column')
                t_ms = timestamp_ms(dt)
                values = []
                for key in ('open', 'high', 'low', 'close'):
                    v = field(row, {key, key+'bid'})
                    if v is None:
                        raise ValueError(f'Missing {key} column')
                    values.append(float(v))
                o,h,l,c = values
                if min(values) <= 0 or h < max(o,c,l) or l > min(o,c,h):
                    raise ValueError('Invalid OHLC values')
                if t_ms % 60000:
                    raise ValueError('Not aligned to minute boundary')
                found.append((t_ms,o,h,l,c))
            except Exception as e:
                raise ValueError(f'{csv_file.name} line {line_no}: {e}') from e
    if not found:
        raise ValueError('CSV contains no candle rows')
    found.sort()
    times = [x[0] for x in found]
    if len(times) != len(set(times)):
        raise ValueError('Duplicate candle timestamps')
    diffs = [(b-a)//60000 for a,b in zip(times,times[1:]) if 0 < b-a <= 3600000]
    if not diffs or min(diffs) not in (1,5,15):
        raise ValueError('Expected 1-minute, 5-minute, or 15-minute OHLC export (not H1 or tick)')
    return found

def convert(input_file, month, source='Dukascopy'):
    if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
        raise ValueError('Month must be YYYY-MM')
    rows = read_rows(input_file)
    selected = [r for r in rows if datetime.fromtimestamp(r[0]/1000, timezone.utc).strftime('%Y-%m') == month]
    if len(selected) < 40:
        raise ValueError(f'Only {len(selected)} rows found for {month}; nothing changed')
    buckets = {}
    for row in selected:
        bucket = row[0] // 900000 * 900000
        buckets.setdefault(bucket, []).append(row)
    bars=[]
    for t, rr in sorted(buckets.items()):
        rr.sort(key=lambda x:x[0])
        bars.append([t,round(rr[0][1],5),round(max(r[2] for r in rr),5),round(min(r[3] for r in rr),5),round(rr[-1][4],5)])
    if len(bars) < 10:
        raise ValueError('Too few candles; nothing changed')
    # Do not accidentally overwrite a full month with a one-day CSV.
    existing = DATA / f'{month}.json'
    if existing.exists():
        old = json.loads(existing.read_text(encoding='utf-8'))
        if len(bars) < len(old.get('bars',[])):
            raise ValueError(f'Existing {month} has {len(old["bars"])} candles; new export has only {len(bars)}. Refusing replacement.')
    DATA.mkdir(parents=True, exist_ok=True)
    obj = {'symbol':'XAUUSD','source':source,'side':'bid','timeframe':'15m','timezone':'UTC','month':month,'bars':bars}
    existing.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'Imported {month}: {len(bars)} 15m candles from {input_file}')

def update_manifest():
    valid=[]
    for path in sorted(DATA.glob('????-??.json')):
        try:
            o=json.loads(path.read_text(encoding='utf-8'))
            if o.get('month') == path.stem and o.get('bars'):
                valid.append(path.stem)
        except (OSError,ValueError):
            continue
    obj={'symbol':'XAUUSD','source':'Dukascopy','side':'bid','baseTimeframe':'15m','timezone':'UTC','months':valid}
    (DATA/'manifest.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Manifest:',', '.join(valid))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('csv',type=Path)
    parser.add_argument('--month',required=True)
    args=parser.parse_args()
    convert(args.csv,args.month)
    update_manifest()
