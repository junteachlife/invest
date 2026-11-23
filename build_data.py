#!/usr/bin/env python3
"""Build compact monthly XAU/USD 15m OHLC JSON from Dukascopy 1m CSV.
Uses historical bid OHLC; periods are aligned to UTC midnight.
"""
import argparse
import calendar
import csv
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'xauusd'


def months(start, end):
    y, m = map(int, start.split('-'))
    ey, em = map(int, end.split('-'))
    if not (1 <= m <= 12 and 1 <= em <= 12) or (y, m) > (ey, em):
        raise ValueError('Invalid month range')
    result = []
    while (y, m) <= (ey, em):
        result.append(f'{y:04d}-{m:02d}')
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if len(result) > 12:
        raise ValueError('Run at most 12 months per workflow')
    return result


def aggregate_csv(path, target):
    points = {}
    with path.open(newline='', encoding='utf-8-sig') as file:
        for row in csv.DictReader(file):
            try:
                ts = float(row['timestamp'])
                if ts < 1e11:
                    ts *= 1000
                ts = int(ts)
                o, h, l, c = (float(row[k]) for k in ('open', 'high', 'low', 'close'))
                if min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
                    continue
                bucket = ts // 900000 * 900000
                if datetime.fromtimestamp(bucket / 1000, timezone.utc).strftime('%Y-%m') != target:
                    continue
                points.setdefault(bucket, []).append((ts, o, h, l, c))
            except (ValueError, KeyError, OverflowError):
                continue
    data = []
    for t, rows in sorted(points.items()):
        rows.sort(key=lambda x: x[0])
        data.append([t, round(rows[0][1], 5), round(max(r[2] for r in rows), 5),
                     round(min(r[3] for r in rows), 5), round(rows[-1][4], 5)])
    return data


def make_one(month):
    year, mon = map(int, month.split('-'))
    to_year, to_mon = (year + 1, 1) if mon == 12 else (year, mon + 1)
    start = f'{year:04d}-{mon:02d}-01'
    end = f'{to_year:04d}-{to_mon:02d}-01'
    with tempfile.TemporaryDirectory() as tmp:
        print(f'Downloading XAUUSD {month} (Dukascopy bid M1)', flush=True)
        cmd = ['npx', '--yes', 'dukascopy-node', '-i', 'xauusd', '-from', start,
               '-to', end, '-t', 'm1', '-f', 'csv', '-p', 'bid', '-dir', tmp,
               '--cache', '--retries', '3', '--batch-pause', '2000']
        subprocess.run(cmd, check=True, timeout=2400)
        files = list(Path(tmp).rglob('*.csv'))
        if len(files) != 1:
            raise RuntimeError(f'Expected one downloaded CSV, got {len(files)}: {files}')
        bars = aggregate_csv(files[0], month)
        if len(bars) < 10:
            raise RuntimeError(f'Not enough valid data for {month} ({len(bars)} bars); existing files left untouched')
    DATA.mkdir(parents=True, exist_ok=True)
    dest = DATA / f'{month}.json'
    obj = {'symbol': 'XAUUSD', 'source': 'Dukascopy', 'side': 'bid', 'timeframe': '15m',
           'timezone': 'UTC', 'month': month, 'bars': bars}
    dest.write_text(json.dumps(obj, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
    print(f'Wrote {dest} ({len(bars)} bars)', flush=True)


def manifest():
    DATA.mkdir(parents=True, exist_ok=True)
    valid = []
    for p in sorted(DATA.glob('????-??.json')):
        try:
            payload = json.loads(p.read_text('utf-8'))
            if payload.get('bars') and payload.get('month') == p.stem:
                valid.append(p.stem)
        except (OSError, json.JSONDecodeError):
            continue
    obj = {'symbol': 'XAUUSD', 'source': 'Dukascopy', 'side': 'bid',
           'baseTimeframe': '15m', 'timezone': 'UTC', 'months': valid}
    (DATA / 'manifest.json').write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Available months:', ', '.join(valid), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-month', dest='from_month')
    parser.add_argument('--to-month', dest='to_month')
    parser.add_argument('--recent', action='store_true', help='Update current and previous UTC month')
    args = parser.parse_args()
    if args.recent:
        now = datetime.now(timezone.utc)
        cy, cm = now.year, now.month
        py, pm = (cy - 1, 12) if cm == 1 else (cy, cm - 1)
        targets = months(f'{py:04d}-{pm:02d}', f'{cy:04d}-{cm:02d}')
    else:
        if not args.from_month or not args.to_month:
            parser.error('Provide both --from-month and --to-month')
        targets = months(args.from_month, args.to_month)
    for target in targets:
        make_one(target)
    manifest()


if __name__ == '__main__':
    main()
