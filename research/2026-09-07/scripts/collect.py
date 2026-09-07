"""Bounded read-only public data collection. Never sends Telegram or trades.

Snapshots preserve unfiltered pages, errors and retrieval clocks. Candle
backfill targets the historical signal window, not today's surviving tokens.
Free GeckoTerminal API endpoint contract used by the existing hunter; optional
CoinGecko demo key via COINGECKO_DEMO_API_KEY, passed in headers only.
"""
import argparse, concurrent.futures, datetime as dt, hashlib, json, math, os, pathlib, time, urllib.error, urllib.parse, urllib.request
from replay import cohort
ROOT=pathlib.Path(__file__).resolve().parents[1]

def fetch(url,headers=None):
    started=dt.datetime.now(dt.timezone.utc).isoformat()
    meta={'url':url,'requested_at':started,'ok':False}
    try:
        req=urllib.request.Request(url,headers={'Accept':'application/json','User-Agent':'memehunter-research/2026-09-07',**(headers or {})})
        with urllib.request.urlopen(req,timeout=12) as res:raw=res.read();meta['http_status']=res.status
        meta['fetched_at']=dt.datetime.now(dt.timezone.utc).isoformat();meta['sha256']=hashlib.sha256(raw).hexdigest()
        d=json.loads(raw)
        if not isinstance(d,dict) or 'data' not in d:meta['error']='invalid_response_schema';return meta,None
        meta['ok']=True
        (ROOT/'raw'/('api-'+meta['sha256']+'.json')).write_bytes(raw)
        return meta,d
    except Exception as e:
        meta['error_type']=type(e).__name__
        if isinstance(e,urllib.error.HTTPError):
            meta['http_status']=e.code
            meta['retry_after']=e.headers.get('Retry-After')
        return meta,None

def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['snapshots','candles']);p.add_argument('--limit',type=int,default=12)
    p.add_argument('--execute',action='store_true',help='Actually request data; otherwise only write plan')
    p.add_argument('--interval',type=float,default=13,help='Seconds between requests; conservative public API default')
    p.add_argument('--sample',type=int,default=0,help='Outcome-independent stratified pilot: all HOT then temporal ALERT sample')
    p.add_argument('--provider',choices=['geckoterminal','coingecko'],default='geckoterminal');a=p.parse_args()
    if a.limit<1:raise SystemExit('--limit must be positive')
    base='https://api.geckoterminal.com/api/v2' if a.provider=='geckoterminal' else 'https://api.coingecko.com/api/v3/onchain'
    headers={}
    if a.provider=='coingecko' and a.execute:
        key=os.getenv('COINGECKO_DEMO_API_KEY')
        if not key:raise SystemExit('COINGECKO_DEMO_API_KEY required; key must stay in environment')
        headers={'x-cg-demo-api-key':key}
    plan=[]
    if a.mode=='snapshots':
        for route in ['new_pools','trending_pools','pools']:
            for page in [1,2,3]:
                query={'page':page,'include':'base_token,quote_token,dex'}
                plan.append({'url':base+'/networks/robinhood/'+route+'?'+urllib.parse.urlencode(query),'route':route,'page':page})
    else:
        alerts=[json.loads(l) for l in (ROOT/'historical_alerts.jsonl').read_text().splitlines()]
        # Outcome-independent deterministic ordering; all first high-tier token signals remain in manifest.
        for s in cohort(alerts):
            entry=math.ceil((s['available_ts']+60)/60)*60
            params={'aggregate':1,'limit':1000,'currency':'usd','token':s['token'],
                'before_timestamp':entry+4*3600+120,'include_empty_intervals':'true'}
            plan.append({'url':base+'/networks/robinhood/pools/'+s['pool']+'/ohlcv/minute?'+urllib.parse.urlencode(params),
                'pool':s['pool'],'token':s['token'],'tier':s['tier'],'entry_target_ts':entry,'signal_available_ts':s['available_ts']})
    (ROOT/f'{a.mode}-request-plan.json').write_text(json.dumps(plan,indent=2))
    if a.sample and a.mode=='candles':
        hot=[r for r in plan if r['tier']=='HOT'];other=[r for r in plan if r['tier']!='HOT']
        remaining=max(0,a.sample-len(hot))
        selected=hot+[other[math.floor((i+.5)*len(other)/remaining)] for i in range(remaining)] if remaining else hot
        plan=sorted(selected,key=lambda r:r['signal_available_ts'])
        (ROOT/'candles-selected-plan.json').write_text(json.dumps(plan,indent=2))
    if not a.execute:
        print(json.dumps({'planned':len(plan),'executed':0,'mode':a.mode}));return
    results=[];failed=0
    def run_item(item):
        meta,d=fetch(item['url'],headers);meta.update({k:v for k,v in item.items() if k!='url'})
        if d is not None and a.mode=='candles':
            rows=d.get('data',{}).get('attributes',{}).get('ohlcv_list')
            identities={v.get('address','').lower() for v in d.get('meta',{}).values() if isinstance(v,dict)}
            if item['token'].lower() not in identities:
                meta.update({'ok':False,'error':'token_not_verified_by_response_meta'})
            elif not isinstance(rows,list):meta.update({'ok':False,'error':'missing_ohlcv_list'})
            else:
                out={'pool':item['pool'],'token':item['token'],'currency':'usd','interval_s':60,
                    'fetched_at':meta['fetched_at'],'source_url':item['url'],'raw_sha256':meta['sha256'],'rows':rows}
                (ROOT/'candles').mkdir(exist_ok=True)
                (ROOT/'candles'/(item['pool']+'.json')).write_text(json.dumps(out))
                meta['candle_rows']=len(rows)
                meta['covers_entry_timestamp']=any(r[0]==item['entry_target_ts'] for r in rows)
        return meta
    # At most 3 in flight, and globally no more than one new request per 2.3s.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pending=[];last_submit=0
        for item in plan[:a.limit]:
            while pending and (pending[0].done() or len(pending)>=3):
                meta=pending.pop(0).result();results.append(meta);print(json.dumps(meta),flush=True)
                failed=0 if meta['ok'] else failed+1
            if failed>=3:break
            cache=ROOT/'candles'/(item.get('pool','')+'.json')
            if a.mode=='candles' and cache.exists():
                results.append({**item,'ok':True,'cached':True});continue
            time.sleep(max(0,a.interval-(time.monotonic()-last_submit)))
            pending.append(ex.submit(run_item,item));last_submit=time.monotonic()
        for fut in pending:
            meta=fut.result();results.append(meta);print(json.dumps(meta),flush=True)
    (ROOT/'results'/f'collection-{a.mode}.json').write_text(json.dumps({'provider':a.provider,
        'planned':len(plan),'attempted':len(results),'success':sum(r['ok'] for r in results),
        'circuit_breaker':failed>=3,'attempts':results},indent=2))

if __name__=='__main__':main()
