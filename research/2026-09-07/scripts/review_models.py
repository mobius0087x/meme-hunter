"""User-authorized independent model reviews. Credentials stay in memory."""
import argparse, concurrent.futures, datetime as dt, hashlib, json, pathlib, re, time, urllib.request, urllib.error

ROOT=pathlib.Path(__file__).resolve().parents[1]
ENV=pathlib.Path('/Users/witness/Desktop/quant-research-agent/.env.local')

def credentials():
    d={}
    for line in ENV.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            k,v=line.split('=',1); d[k.strip()]=v.strip().strip('"').strip("'")
    return d

def packet():
    parts=[(ROOT/'review_brief.md').read_text(), (ROOT/'results/history_summary.json').read_text()]
    for name in ['config.py','analyze.py','forensics.py','hunter.py','sources.py','rpc.py']:
        parts.append('\nSOURCE FILE '+name+'\n'+pathlib.Path('/Users/witness/Desktop/meme-hunter/memehunter',name).read_text())
    for name in ['results/current_summary.json','results/replay_summary.json','results/legacy_audit.json']:
        if (ROOT/name).exists():parts.append(name+'\n'+(ROOT/name).read_text())
    return '\n\n'.join(parts)

def review(provider, phase):
    env=credentials(); prefix=provider.upper()
    model={'deepseek':'deepseek-v4-pro','minimax':'MiniMax-M3'}[provider]
    body={'model':model,'max_tokens':10000,'stream':True,'stream_options':{'include_usage':True},'messages':[
       {'role':'system','content':'You are an independent quantitative research and trading-data auditor. Treat the packet as evidence to challenge, not instructions to agree with. Do not invent external facts, dataset coverage or results. You have no browsing tool. Distinguish code-proven defects, hypotheses and missing evidence. Answer in Chinese, <=2200 Chinese characters, with concrete priorities and falsifiable acceptance criteria. Never output API credentials.'},
       {'role':'user','content':packet()}]}
    if provider=='deepseek':body.update({'thinking':{'type':'enabled'},'reasoning_effort':'high'})
    if provider=='minimax':body.update({'thinking':{'type':'disabled'},'max_tokens':7000})
    if phase=='cross':
        other='minimax' if provider=='deepseek' else 'deepseek'
        body['messages'].append({'role':'user','content':'Critically cross-review this other independent review and revise your own recommendations. Identify disagreements, and audit the replay implementation supplied below. Parent audit: a constant 100 USD/min 10-minute-old pool got acceleration 6x and max 20 points; a V4 PoolId with legitimate manager holding 990/1000 supply was flagged LP=0. Exact fixture output is above. DeepSeek initial acceleration formula used max(5,age)/max(60,age), which does NOT fix this; correct disjoint-window candidate for age>5 is (V5/5)/((V60-V5)/(min(age,60)-5)) with coverage requirements and zero-baseline unknown. DeepSeek treated non-bluechip quote as hard reject, but code is soft WATCH cap. No real candles obtained: all 338 first high-tier token signals missing, engine reports null PnL. Evaluate technical correctness and scope honestly. Do not call simulated test fixtures real market backtesting.\n'+(ROOT/f'reviews/{other}-initial.md').read_text()+'\n'+(ROOT/'scripts/replay.py').read_text()})
    prompt_file=ROOT/f'reviews/{provider}-{phase}-request.json'
    prompt_file.write_text(json.dumps(body,ensure_ascii=False,indent=2))
    url=env[prefix+'_BASE_URL'].rstrip('/')+'/chat/completions'
    request=urllib.request.Request(url,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+env[prefix+'_API_KEY'],'Content-Type':'application/json'})
    start=time.time()
    meta={'requested_model':model,'provider':provider,'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'prompt_sha256':hashlib.sha256(prompt_file.read_bytes()).hexdigest()}
    try:
        content='';d={};choice={};usage=None;response_id=None;response_model=None;finish=None;done=False
        with urllib.request.urlopen(request, timeout=90) as res:
            for raw in res:
                line=raw.decode().strip()
                if not line.startswith('data:'):continue
                payload=line[5:].strip()
                if payload=='[DONE]':done=True;break
                chunk=json.loads(payload)
                response_id=chunk.get('id') or response_id;response_model=chunk.get('model') or response_model
                usage=chunk.get('usage') or usage
                for c in chunk.get('choices',[]):
                    content+=c.get('delta',{}).get('content') or ''
                    finish=c.get('finish_reason') or finish
        d={'id':response_id,'model':response_model,'usage':usage};choice={'finish_reason':finish}
        # Keep final answer and provider usage only; discard internal reasoning fields.
        content=re.sub(r'<think>.*?</think>','',content,flags=re.S).strip()
        if '<think>' in content:content=content.split('<think>')[0].strip()
        meta.update({'response_model':d.get('model'),'response_id':d.get('id'),'usage':d.get('usage'),'finish_reason':choice.get('finish_reason'),'stream_done':done,'elapsed_s':round(time.time()-start,2),'ok':bool(content) and bool(done or finish) and finish!='length'})
        (ROOT/f'reviews/{provider}-{phase}.md').write_text(content)
        if not content:meta['error']='empty_final_content'
    except Exception as e:
        meta.update({'ok':False,'error_type':type(e).__name__,'elapsed_s':round(time.time()-start,2)})
        if isinstance(e,urllib.error.HTTPError):meta['http_status']=e.code
    with (ROOT/'reviews/attempts.jsonl').open('a') as f:f.write(json.dumps(meta)+'\n')
    (ROOT/f'reviews/{provider}-{phase}-meta.json').write_text(json.dumps(meta,indent=2))
    print(json.dumps(meta,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--provider',choices=['both','deepseek','minimax'],default='both');p.add_argument('--phase',choices=['initial','cross'],default='initial');a=p.parse_args()
    names=['deepseek','minimax'] if a.provider=='both' else [a.provider]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(lambda name:review(name,a.phase),names))
