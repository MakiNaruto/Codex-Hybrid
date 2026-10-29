"""Opt-in, five short live probes of current route/adapters. No retries."""
import json,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from gateway.server import route,adapted_stream
from gateway.transport import FreshProxyOpener,error_event

def main():
 s=json.loads((Path.home()/'.codex-hybrid/settings.json').read_text()); results=[]; total=0
 dest=Path(__file__).with_name('bounded-routing-r2-preflight.json')
 for model in s['models']:
  if model in s['official_models'] or 'openrouter' in model.lower(): continue
  if total>8000: break
  body={'model':model,'input':[{'role':'user','content':'Reply exactly R2_READY_731.'}],'stream':True,'store':False,'max_output_tokens':128,'reasoning':{'effort':'low'}}
  r={'model':model,'case':'fresh_route_adapter','started':time.time()}; text=[]; terminal=False
  try:
   url,payload,headers,adapt=route(body,{'Authorization':'Bearer synthetic-bounded-probe'},s)
   r['output_cap']=payload.get('max_output_tokens')
   with FreshProxyOpener(s.get('upstream_proxy')).open(urllib.request.Request(url,data=json.dumps(payload).encode(),headers=headers),timeout=40) as response:
    r['http_status']=response.status
    for raw,e in adapted_stream(response,adapt):
     if e.get('type')=='response.output_text.delta': text.append(e.get('delta',''))
     if e.get('type') in {'response.completed','response.failed','response.incomplete'}:
      f=e.get('response',{}); r.update(status=f.get('status'),usage=f.get('usage'),returned_model=f.get('model')); terminal=True
     if e.get('type')=='error': r['status']='error'
   r['text']=''.join(text); r['passed']=r.get('status')=='completed' and r['text'].strip()=='R2_READY_731'
  except Exception as err: r.update(error=error_event(err,'preflight'),passed=False)
  r['elapsed_ms']=round((time.time()-r['started'])*1000); results.append(r)
  usage=r.get('usage') or {}; total+=usage.get('total_tokens',0)
  dest.write_text(json.dumps({'results':results,'reported_third_party_tokens':total},ensure_ascii=False,indent=2)); print(json.dumps(r,ensure_ascii=False),flush=True)
  if not r.get('usage'): print('STOP: missing usage; no further preflight requests',flush=True); break
if __name__=='__main__': main()
