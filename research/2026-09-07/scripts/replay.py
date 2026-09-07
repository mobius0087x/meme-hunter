"""Price-only event replay, not a claim of executable strategy profitability.

Candle files: candles/<pool>.json = {pool, token, currency:'usd', interval_s:60,
fetched_at, source_url, rows:[[start,o,h,l,c,usd_volume],...]}. All rows must be
chronological after sorting; duplicate timestamps and gaps fail closed. Signal
eligibility uses only recorded fields. No historical OHLCV => coverage failure.
"""
import argparse, collections, json, math, pathlib, statistics
ROOT=pathlib.Path(__file__).resolve().parents[1]

def validate_bar(row):
    if len(row)!=6 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in row):return 'invalid_numbers'
    t,o,h,l,c,v=row
    if t<0 or int(t)!=t or min(o,h,l,c)<=0 or v<0:return 'invalid_domain'
    if not l<=min(o,c)<=max(o,c)<=h:return 'invalid_ohlc'
    if h/max(o,c)>100 or min(o,c)/l>100:return 'suspect_wick_requires_review'
    return None

def replay(signal, data, *, horizon_s=3600, latency_s=60, cost_bps=200, gas_usd=0,
           notional_usd=100, stop=.20, target=.40, participation=.01, intrabar_policy='stop_first'):
    out={'pool':signal['pool'],'token':signal['token'],'symbol':signal.get('symbol'),
         'signal_ts':signal['ts'],'available_ts':signal['available_ts'],'status':'unknown',
         'net_return':None,'cost_bps_per_side':cost_bps,'horizon_s':horizon_s,
         'gas_usd_each_side':gas_usd,'latency_s':latency_s,'intrabar_policy':intrabar_policy,'quiet_bars':0,
         'notional_usd':notional_usd,'participation_cap':participation,
         'stop_fraction':stop,'target_fraction':target if math.isfinite(target) else None}
    def fail(status):out['status']=status;return out
    if not (0<=cost_bps<10000 and 0<=gas_usd<notional_usd and notional_usd>0 and latency_s>=0 and 0<participation<=1 and 0<=stop<=1 and target>=0 and intrabar_policy in ('stop_first','target_first')):return fail('invalid_parameters')
    if data is None:return fail('missing_candles')
    if data.get('pool','').lower()!=signal['pool'].lower() or data.get('token','').lower()!=signal['token'].lower():return fail('identity_mismatch')
    if data.get('currency')!='usd':return fail('wrong_currency')
    interval=data.get('interval_s')
    if not isinstance(interval,int) or interval<=0 or horizon_s%interval:return fail('unsupported_interval')
    if not data.get('source_url') or not data.get('fetched_at'):return fail('missing_provenance')
    rows=data.get('rows',[])
    if not rows:return fail('empty_candles')
    # Preserve bad rows as reasons, never skip a bad bar and select the next favorable one.
    indexed={}
    for row in rows:
        if not isinstance(row,list) or not row:return fail('malformed_candles')
        t=row[0]
        if not isinstance(t,(float,int)) or not math.isfinite(t):return fail('malformed_timestamp')
        if t%interval:return fail('unaligned_timestamp')
        if t in indexed:return fail('duplicate_timestamp')
        indexed[t]=row
    earliest=signal['available_ts']+latency_s
    entry_ts=math.ceil(earliest/interval)*interval
    out['entry_ts']=entry_ts;out['exit_due_ts']=entry_ts+horizon_s
    previous=indexed.get(entry_ts-interval)
    if previous is None:return fail('missing_pre_entry_bar')
    if validate_bar(previous):return fail('invalid_pre_entry_bar')
    # Capacity gate uses the last completed bar, never future entry-bar volume.
    if previous[5]*participation<notional_usd:return fail('entry_capacity_rejected')
    entry=indexed.get(entry_ts)
    if entry is None:return fail('missing_entry_bar')
    reason=validate_bar(entry)
    if reason:return fail(reason)
    if entry[5]<=0:return fail('unfilled_entry_no_trades')
    if entry[5]*participation<notional_usd:return fail('unfilled_entry_capacity')
    raw_entry=entry[1];stop_px=raw_entry*(1-stop);target_px=raw_entry*(1+target)
    out['entry_price']=raw_entry
    cost=cost_bps/10000
    units=(notional_usd-gas_usd)*(1-cost)/raw_entry
    if units<=0:return fail('cost_exceeds_notional')
    ambiguous=False;observed_high=raw_entry;observed_low=raw_entry
    for t in range(entry_ts,entry_ts+horizon_s+interval,interval):
        row=indexed.get(t)
        if row is None:return fail('censored_missing_bar_after_entry')
        reason=validate_bar(row)
        if reason:return fail('censored_'+reason)
        if row[5]<=0:
            if t==entry_ts+horizon_s:return fail('censored_time_exit_no_trades')
            out['quiet_bars']+=1
            continue
        _,o,h,l,c,v=row
        if t==entry_ts+horizon_s:
            exit_px=o;why='time_exit'
        elif o<=stop_px:
            exit_px=o;why='gap_stop'
        elif o>=target_px:
            exit_px=target_px;why='target_gap_conservative'
        elif l<=stop_px:
            exit_px=stop_px;why='stop';ambiguous=h>=target_px
            if ambiguous and intrabar_policy=='target_first':exit_px=target_px;why='target_optimistic_ambiguity'
        elif h>=target_px:
            exit_px=target_px;why='target'
        else:
            observed_high=max(observed_high,h);observed_low=min(observed_low,l)
            continue
        # Ex-post fill proxy, not a signal feature: reported traded volume limits
        # simulated fills but does NOT prove depth, an available route, or sellability.
        if v*participation<units*exit_px:
            return fail('censored_exit_capacity')
        proceeds=units*exit_px*(1-cost)-gas_usd
        out.update({'status':'priced_proxy','exit_ts':t,'exit_price':exit_px,'exit_reason':why,
            'intrabar_ambiguous':ambiguous,'net_return':proceeds/notional_usd-1,
            'gross_price_return':exit_px/raw_entry-1})
        return out
    return fail('unreachable')

def aggregate(rows):
    priced=[r['net_return'] for r in rows if r['status']=='priced_proxy']
    n=len(rows);k=len(priced);wins=sum(x>0 for x in priced)
    return {'eligible':n,'priced':k,'coverage':k/n if n else 0,
      'status_counts':dict(collections.Counter(r['status'] for r in rows)),
      'conditional_mean_return':statistics.mean(priced) if priced else None,
      'conditional_median_return':statistics.median(priced) if priced else None,
      'conditional_win_rate':wins/k if k else None,
      'ambiguous_priced_count':sum(bool(r.get('intrabar_ambiguous')) for r in rows if r['status']=='priced_proxy'),
      'ambiguous_priced_rate':sum(bool(r.get('intrabar_ambiguous')) for r in rows if r['status']=='priced_proxy')/k if k else None,
      'censored_count':sum(r['status'].startswith('censored_') for r in rows),
      'all_sample_win_rate_bounds':[wins/n,(wins+n-k)/n] if n else None,
      'unconditional_mean_return':None,
      'warning':'Conditional price replay only. Unknown outcomes retained; no executable PnL or population alpha claim.'}

def cohort(alerts):
    seen=set();out=[]
    for r in sorted(alerts,key=lambda r:(r['available_ts'],r['ts'],r['pool'])):
        if r['tier'] not in ('ALERT','HOT'):continue
        key=r['token'].lower()
        if key in seen:continue
        seen.add(key);out.append(r)
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--candles-dir',type=pathlib.Path,default=ROOT/'candles');p.add_argument('--selected-plan',type=pathlib.Path);a=p.parse_args()
    alerts=[json.loads(s) for s in (ROOT/'historical_alerts.jsonl').read_text().splitlines()]
    signals=cohort(alerts);results={}
    if a.selected_plan:
        selected={(r['pool'],r['token']) for r in json.loads(a.selected_plan.read_text())}
        signals=[s for s in signals if (s['pool'],s['token']) in selected]
    for horizon in [900,3600,14400]:
        for cost in [50,200,500]:
            rows=[]
            for s in signals:
                path=a.candles_dir/(s['pool']+'.json')
                d=json.loads(path.read_text()) if path.exists() else None
                rows.append(replay(s,d,horizon_s=horizon,cost_bps=cost))
            name=f'h{horizon//60}m-c{cost}bps'
            results[name]=aggregate(rows)
            (ROOT/'results'/f'replay-{name}.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    (ROOT/'results/replay_summary.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))

if __name__=='__main__':main()
