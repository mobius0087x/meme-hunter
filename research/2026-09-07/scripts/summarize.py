"""Build pilot results from the preselected identities, preserving all exclusions."""
import collections, datetime as dt, json, pathlib, statistics
from replay import cohort, replay, aggregate
ROOT=pathlib.Path(__file__).resolve().parents[1]

def main():
    alerts=[json.loads(s) for s in (ROOT/'historical_alerts.jsonl').read_text().splitlines()]
    universe=cohort(alerts)
    selected=json.loads((ROOT/'candles-selected-plan.json').read_text())
    selected_keys={(r['pool'],r['token']) for r in selected}
    signals=[r for r in universe if (r['pool'],r['token']) in selected_keys]
    candles={}
    for s in signals:
        f=ROOT/'candles'/(s['pool']+'.json')
        candles[s['pool']]=json.loads(f.read_text()) if f.exists() else None
    scenarios={};allrows=[]
    for hold in [900,3600,14400]:
        for cost in [50,200,500]:
            for strategy in ['fixed_hold','stop20_target40']:
                rows=[replay(s,candles[s['pool']],horizon_s=hold,cost_bps=cost,
                    stop=1 if strategy=='fixed_hold' else .2,target=float('inf') if strategy=='fixed_hold' else .4) for s in signals]
                name=f'{strategy}-h{hold//60}m-c{cost}bps-l60s'
                for r in rows:r['scenario']=name
                allrows.extend(rows);scenarios[name]=aggregate(rows)
    for latency in [0,120,300]:
        name=f'stop20_target40-h60m-c200bps-l{latency}s'
        rows=[replay(s,candles[s['pool']],horizon_s=3600,cost_bps=200,latency_s=latency) for s in signals]
        for r in rows:r['scenario']=name
        allrows.extend(rows);scenarios[name]=aggregate(rows)
    name='stop20_target40-h60m-c200bps-l60s-target_first'
    rows=[replay(s,candles[s['pool']],horizon_s=3600,cost_bps=200,intrabar_policy='target_first') for s in signals]
    for r in rows:r['scenario']=name
    allrows.extend(rows);scenarios[name]=aggregate(rows)
    # Explicit capacity/size stress, not a search for the most profitable setting.
    for notional in [25,100,500]:
        for cap in [.01,.05]:
            name=f'stop20_target40-h60m-c200bps-l60s-size{notional}-cap{cap}'
            rows=[replay(s,candles[s['pool']],horizon_s=3600,cost_bps=200,notional_usd=notional,participation=cap) for s in signals]
            for r in rows:r['scenario']=name
            allrows.extend(rows);scenarios[name]=aggregate(rows)
    primary='stop20_target40-h60m-c200bps-l60s'
    primary_rows=[r for r in allrows if r['scenario']==primary]
    per_tier={}
    for tier in ['HOT','ALERT']:
        ids={r['token'] for r in signals if r['tier']==tier}
        per_tier[tier]=aggregate([r for r in primary_rows if r['token'] in ids])
    summary={
        'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'historical_first_high_tier_token_universe':len(universe),'preselected_pilot_n':len(signals),
        'selection':'All 21 HOT + 27 ALERT sampled at equally spaced chronological indices, chosen before reading their OHLCV outcomes. Not population-weighted.',
        'selected_tiers':dict(collections.Counter(s['tier'] for s in signals)),
        'selected_weeks':dict(collections.Counter(dt.datetime.fromtimestamp(s['ts'],dt.timezone.utc).strftime('%G-W%V') for s in signals)),
        'selected_dexes':dict(collections.Counter(s['dex'] for s in signals)),
        'downloaded_selected_files':sum(d is not None for d in candles.values()),
        'downloaded_nonempty_selected_files':sum(d is not None and bool(d['rows']) for d in candles.values()),
        'downloaded_candle_rows':sum(len(d['rows']) for d in candles.values() if d is not None),
        'primary_scenario':primary,'primary':scenarios[primary],'primary_per_tier':per_tier,
        'scenarios':scenarios,
        'interpretation':'Historical alert-conditioned OHLCV execution proxy pilot. Sparse/filtered original selection; missing/unfilled exits; taxes/routes and real depth unknown. No population win rate, alpha, or live-executable PnL conclusion.',
        'tests_are_synthetic_not_market_data':True}
    (ROOT/'results/final_summary.json').write_text(json.dumps(summary,indent=2))
    (ROOT/'results/pilot_event_results.jsonl').write_text(''.join(json.dumps(r,allow_nan=False)+'\n' for r in allrows))
    (ROOT/'results/primary_events.json').write_text(json.dumps(primary_rows,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k!='scenarios'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
