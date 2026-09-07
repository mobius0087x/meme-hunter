"""Parse saved public web table observations; do not merge asynchronous prices."""
import collections, datetime as dt, json, pathlib, re, urllib.parse
ROOT=pathlib.Path(__file__).resolve().parents[1]

def money(s):
    s=s.strip().replace('$','').replace(',','')
    try:
        scale={'K':1e3,'M':1e6,'B':1e9}.get(s[-1],1)
        return float(s[:-1] if scale!=1 else s)*scale
    except (ValueError,IndexError):return None

def main():
    sources={
        'new-pools':('web-samples.txt','New Crypto Pools on Robinhood','https://www.geckoterminal.com/explore/new-crypto-pools/robinhood'),
        'stock-pairs':('web-board.txt','Top Stock Paired Tokens Coins on Robinhood','https://www.geckoterminal.com/category/stock-paired-tokens/robinhood'),
        'trending':('web-trending.txt','Top Robinhood Pools Trending Today','https://www.geckoterminal.com/robinhood/pools')}
    rows=[]
    for group,(file,title,url) in sources.items():
        raw=(ROOT/'raw'/file).read_text()
        sections=raw.split('-'*80)
        section=next(s for s in sections if s.lstrip().startswith(title))
        links=(ROOT/'raw'/f'links-{group}.txt').read_text().split('-'*80)
        linkmap={}
        for s in links:
            m=re.search(r'Source: click\(.*?"id":\s*(\d+)',s)
            u=re.search(r'https://www\.geckoterminal\.com/robinhood/pools/(0x[a-fA-F0-9]+)(?:\?token_address=(0x[a-fA-F0-9]+))?',s)
            if m:
                pairtitle=re.search(r'^\s*(\S+/\S+) - ',s)
                linkmap[int(m[1])]={'pool':u[1].lower() if u else None,'token':u[2].lower() if u and u[2] else None,'detail_access':'unavailable' if 'Internal Error' in s else 'available','detail_pair':pairtitle[1] if pairtitle else None}
        matches=list(re.finditer(r'cite(\d+)†(\d+)\s*(.*?)',section))
        for i,m in enumerate(matches):
            if not 1<=int(m[2])<=20:continue
            block=section[m.end():matches[i+1].start() if i+1<len(matches) else len(section)]
            vals=[v.strip() for v in re.sub(r'L\d+:\s*','\n',block).splitlines() if v.strip()]
            age=next((v for v in vals if re.fullmatch(r'\d+\s*(m|h|d|mth|mths)',v)),None)
            if age is None:continue
            ageidx=vals.index(age);tail=vals[ageidx+1:]
            amounts=[(j,v) for j,v in enumerate(tail) if re.fullmatch(r'-?\$[\d.,]+[KMB]?',v)]
            liquid=money(amounts[0][1]) if amounts else None
            vol=money(amounts[1][1]) if len(amounts)>1 else None
            # Security UI includes extra percentages; only the final four preceding liquidity map to price windows.
            pcs=[float(v[:-1].replace(',','')) for v in tail[:amounts[0][0]] if re.fullmatch(r'-?[\d.,]+%',v)] if amounts else []
            price_windows=pcs[-4:] if len(pcs)>=4 else None
            match=re.search(r'(\S+/\S+)',m[3]);pair=match[1] if match else m[3]
            n,u=re.fullmatch(r'(\d+)\s*(m|h|d|mth|mths)',age).groups()
            minutes=int(n)*{'m':1,'h':60,'d':1440,'mth':43200,'mths':43200}[u]
            ident=linkmap.get(int(m[1]),{})
            # Reopening a dynamic table can change link IDs; do not attach a different token's pool.
            if group=='trending' and ident.get('detail_pair')!=pair:
                ident={'pool':None,'token':None,'detail_access':'dynamic_table_link_mismatch'}
            rows.append({'group':group,'rank':int(m[2]),'label':m[3],'pair':pair,**ident,
                'reported_age':age,'age_min_approx':minutes,'liquidity_usd_rounded':liquid,
                'volume_24h_usd_rounded':vol,'price_change_24h_pct':price_windows[-1] if price_windows else None,
                'legacy_age_excluded':minutes>240,'source_url':url,'source_row_link_id':int(m[1]),
                'observed_date':'2026-09-07','source_timestamp':None,'kind':'asynchronous_web_snapshot',
                'orientation_verified':False})
    (ROOT/'current_samples.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
    summary={'rows':len(rows),'by_group':{},'unique_identified_pools':len({r['pool'] for r in rows if r.get('pool')}),
      'unresolved_pool_identity_rows':sum(not r.get('pool') for r in rows),
      'distinct_tickers_not_distinct_tokens':len({r['pair'].split('/')[0] for r in rows}),
      'warnings':['Current discovery sample is not a backtest universe.','No synchronous block/time; prices are not cross-page comparable.','Token identity unresolved on many rows; repeated ticker does not establish impostor.','Some table base/quote labels and prices disagree; do not derive token returns from these rows.']}
    for group in sources:
        rs=[r for r in rows if r['group']==group]
        summary['by_group'][group]={'n':len(rs),'age_excluded':sum(r['legacy_age_excluded'] for r in rs),
            'down_24h':sum(r['price_change_24h_pct'] is not None and r['price_change_24h_pct']<0 for r in rs),
            'below_4k_reserves':sum(r['liquidity_usd_rounded'] is not None and r['liquidity_usd_rounded']<4000 for r in rs),
            'pairs':[r['pair'] for r in rs]}
    (ROOT/'results/current_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
