"""Extract actual public feed revisions; retain observations and publication clocks."""
import collections, datetime as dt, hashlib, json, pathlib, statistics, subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = '/Users/witness/Desktop/meme-hunter'

def git(*args):
    return subprocess.check_output(['git', '-C', REPO, *args])

def main():
    commits = git('log', '--reverse', '--format=%H %ct', '--', 'feed/signals.json').decode().splitlines()
    snapshots, observations, events, issues = [], {}, {}, []
    for line in commits:
        sha, published = line.split(); published = int(published)
        raw = git('show', f'{sha}:feed/signals.json')
        d = json.loads(raw)
        (ROOT / 'raw' / f'feed-{sha}.json').write_bytes(raw)
        generated = d.get('generated_at')
        snapshots.append({'commit': sha, 'commit_ts': published, 'generated_at': generated,
            'sha256': hashlib.sha256(raw).hexdigest(), 'cycle': d.get('cycle'),
            'board_n': len(d.get('board', [])), 'alerts_n': len(d.get('alerts', []))})
        for kind in ('board', 'alerts'):
            for r in d.get(kind, []):
                key = (r.get('pool'), r.get('ts'))
                if not all(key):
                    issues.append({'commit': sha, 'reason': 'missing_pool_or_ts'}); continue
                obs = {**r, 'first_seen_commit': sha, 'first_seen_commit_ts': published,
                    'first_seen_feed_ts': generated, 'available_ts': max(published, generated or published, r['ts']),
                    'observed_in': [kind]}
                if key not in observations:
                    observations[key] = obs
                elif kind not in observations[key]['observed_in']:
                    observations[key]['observed_in'].append(kind)
                if kind == 'alerts' and key not in events:
                    events[key] = obs
    obs = sorted(observations.values(), key=lambda r: (r['ts'], r['pool']))
    ev = sorted(events.values(), key=lambda r: (r['ts'], r['pool']))
    for name, rows in [('historical_observations.jsonl',obs),('historical_alerts.jsonl',ev)]:
        (ROOT / name).write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    (ROOT/'history_manifest.json').write_text(json.dumps(snapshots, indent=2))
    times=sorted(set(s['generated_at'] for s in snapshots if s['generated_at']))
    gaps=[(b-a)/60 for a,b in zip(times,times[1:])]
    bypool=collections.Counter(r['pool'] for r in obs)
    summary = {'snapshots':len(snapshots),'observations':len(obs),'alert_events':len(ev),
        'unique_pools':len(bypool), 'unique_tokens':len(set(r['token'] for r in obs)),
        'first_feed_utc':dt.datetime.fromtimestamp(times[0],dt.timezone.utc).isoformat(),
        'last_feed_utc':dt.datetime.fromtimestamp(times[-1],dt.timezone.utc).isoformat(),
        'alert_tiers':dict(collections.Counter(r['tier'] for r in ev)),
        'observations_dex':dict(collections.Counter(r['dex'] for r in obs)),
        'median_cycle_gap_min':statistics.median(gaps),'max_cycle_gap_min':max(gaps),
        'pools_with_2plus_observations':sum(n>=2 for n in bypool.values()),
        'missing_key_issues':issues,
        'limitations':['Filtered board and emitted alerts only; rejected universe was not saved.',
          'Publication uses max(commit time, feed generation, observation); Telegram delivery times unknown.',
          'Alert history repeats stale prices; deduplicated by pool + original observation timestamp.',
          'Later absent pool != zero price, dead pool, or successful exit.',
          'Local git history only, not proof of remote completeness.']}
    (ROOT/'results/history_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__': main()
