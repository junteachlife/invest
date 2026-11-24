#!/usr/bin/env python3
"""Convert EV Trading Labs XAUUSD M15 yearly JSON.GZ into monthly replay JSON.
Existing months are preserved unless --overwrite is given.
"""
import argparse
import gzip
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'xauusd'
REQUIRED = ('ts', 'o', 'h', 'l', 'c')


def load_rows(path):
    opener = gzip.open if path.suffix.lower() == '.gz' else open
    with opener(path, 'rt', encoding='utf-8-sig') as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        # Be tolerant of a wrapper, while rejecting unrelated JSON formats.
        raw = raw.get('data', raw.get('bars', raw.get('candles')))
    if isinstance(raw, dict) and all(k in raw for k in REQUIRED):
        lengths = [len(raw[k]) for k in REQUIRED]
        if len(set(lengths)) != 1:
            raise ValueError('Column arrays have different lengths')
        raw = (dict(zip(REQUIRED, values)) for values in zip(*(raw[k] for k in REQUIRED)))
    if not isinstance(raw, (list, tuple)) and not hasattr(raw, '__iter__'):
        raise ValueError('Unsupported JSON layout. Expected array of ts/o/h/l/c records.')
    return raw


def convert(path, year, overwrite=False):
    by_month = {}
    rejected = 0
    dedup = set()
    for item in load_rows(path):
        try:
            if isinstance(item, dict):
                values = [item[k] for k in REQUIRED]
            elif isinstance(item, (list, tuple)) and len(item) >= 5:
                values = item[:5]
            else:
                rejected += 1; continue
            ts, o, h, l, c = (float(v) for v in values)
            if not all(math.isfinite(x) for x in (ts, o, h, l, c)):
                rejected += 1; continue
            # EV timestamps are UTC seconds; accept milliseconds defensively.
            if ts > 1e11: ts /= 1000
            sec = int(ts)
            # Only closed 15-minute bars on the UTC quarter-hour grid.
            if sec % 900 != 0 or min(o, h, l, c) <= 0 or h < max(o, c) or l > min(o, c):
                rejected += 1; continue
            d = datetime.fromtimestamp(sec, tz=timezone.utc)
            if d.year != year:
                continue
            key = d.strftime('%Y-%m')
            if sec in dedup:
                continue
            dedup.add(sec)
            by_month.setdefault(key, []).append([sec * 1000, round(o, 5), round(h, 5), round(l, 5), round(c, 5)])
        except (KeyError, TypeError, ValueError, OverflowError):
            rejected += 1
    if not by_month:
        raise ValueError(f'No valid XAUUSD M15 candles found for {year}')
    DATA.mkdir(parents=True, exist_ok=True)
    written=[]
    for month, bars in sorted(by_month.items()):
        bars.sort(key=lambda r:r[0])
        dest = DATA / f'{month}.json'
        if dest.exists() and not overwrite:
            print(f'SKIP {month}: existing history preserved')
            continue
        if len(bars)<20:
            raise ValueError(f'Too few candles for {month}: {len(bars)}')
        content = {'symbol':'XAUUSD','source':'EV Trading Labs (Dukascopy-derived)',
                   'side':'bid','timeframe':'15m','timezone':'UTC','month':month,'bars':bars}
        dest.write_text(json.dumps(content, separators=(',',':')), encoding='utf-8')
        print(f'WROTE {month}: {len(bars)} candles')
        written.append(month)
    update_manifest()
    print('Rejected records:',rejected,'New months:', ', '.join(written) or 'none')


def update_manifest():
    DATA.mkdir(parents=True, exist_ok=True)
    valid=[]
    sources=set()
    for p in sorted(DATA.glob('????-??.json')):
        try:
            obj=json.loads(p.read_text(encoding='utf-8'))
            if obj.get('month')==p.stem and len(obj.get('bars',[]))>=20:
                valid.append(p.stem)
                sources.add(obj.get('source','unknown'))
        except (OSError, json.JSONDecodeError):
            pass
    manifest = {'symbol':'XAUUSD','source':next(iter(sources)) if len(sources)==1 else 'Mixed historical sources',
                'side':'bid','baseTimeframe':'15m','timezone':'UTC','months':valid}
    (DATA/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
    print('Manifest months:',len(valid))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='XAUUSD M15 yearly .json.gz file')
    parser.add_argument('--year',type=int,required=True)
    parser.add_argument('--overwrite',action='store_true',help='replace existing months')
    args=parser.parse_args()
    if not args.source.is_file():
        parser.error(f'File missing: {args.source}')
    convert(args.source,args.year,args.overwrite)

if __name__=='__main__':main()
