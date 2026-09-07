"""Offline reproductions against unchanged source, plus historical diagnostics."""
import collections, datetime as dt, json, pathlib, statistics, sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'legacy_source') if (ROOT/'legacy_source').exists() else '/Users/witness/Desktop/meme-hunter')
from memehunter.sources import Pool
from memehunter.analyze import momentum_score
import memehunter.forensics as f

def main():
    now=dt.datetime.now(dt.timezone.utc)
    p=Pool(address='0x'+'a'*64,name='TEST / WETH',dex='uniswap-v4-robinhood',base_symbol='TEST',base_name='Test',base_address='0x'+'b'*40,quote_symbol='WETH',created_at=now-dt.timedelta(minutes=10),liquidity_usd=10000,fdv_usd=20000,market_cap_usd=20000,price_usd=1,price_change={'h1':0},volume={'m5':500,'h1':1000},txns={'h1':{'buys':10,'sells':10,'buyers':10,'sellers':10}})
    score,parts,signals=momentum_score(p)
    manager='0x'+'c'*40;holder='0x'+'d'*40
    class RPC:
        def block_number(self):return 1000000
        def total_supply(self,token):return 1000
        def is_infra(self,addr,latest):return addr==manager
        def is_contract(self,addr):return addr==manager
    old=f._reconstruct
    try:
        f._reconstruct=lambda *args:({manager:990,holder:10},1000)
        grade=f.rug_scan(RPC(),p.base_address,p.address,120)
    finally:f._reconstruct=old
    alerts=[json.loads(l) for l in (ROOT/'historical_alerts.jsonl').read_text().splitlines()]
    by_tier={}
    for tier in ['WATCH','ALERT','HOT']:
        rs=[r for r in alerts if r['tier']==tier]
        by_tier[tier]={'n':len(rs),'age_under_5':sum(r['age_min']<5 for r in rs),
          'age_under_60':sum(r['age_min']<60 for r in rs),
          'claims_acceleration_12x':sum(any('12.0x' in t for t in r['signals']) for r in rs)}
    out={'synthetic_regressions_not_market_performance':{
        'constant_volume_10m_pool':{'input_m5':500,'input_h1':1000,'true_rate_per_min':100,
            'legacy_acceleration_points':parts['acceleration'],'legacy_signals':signals,
            'correct_nonoverlap_acceleration':(500/5)/((1000-500)/(10-5))},
        'v4_poolid_as_wallet':{'pool_id':p.address,'manager_balance':990,'retail_balance':10,
            'supply':1000,'legacy_scanned':grade.scanned,'legacy_flags':grade.rug_flags,
            'expected':'No LP withdrawal inference is possible from PoolId token balance.'}},
      'historical_alert_diagnostics':by_tier}
    assert parts['acceleration']==20 and grade.scanned and any('LP holds only 0.0%' in x for x in grade.rug_flags)
    (ROOT/'results/legacy_audit.json').write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()
