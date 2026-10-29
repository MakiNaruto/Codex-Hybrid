"""Explicit --live: two bounded synthetic tool-history probes; no execution/retry."""
import json,sys,time,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from gateway.server import route,adapted_stream
from gateway.transport import FreshProxyOpener,error_event

def main():
 if sys.argv[1:]!=['--live']:raise SystemExit('Explicit --live required; makes two billable API calls')
 settings=json.loads((Path.home()/'.codex-hybrid/settings.json').read_text());out=[]
 models=['3c33bb50-99b3-4e16-ad4c-6f4b4217bfa8/deepseek-v4-flash','55e8a244-499e-4b7d-af8b-71b734793edb/qwen3.8-max']
 for model in models:
  def definition(description):return {'type':'additional_tools','tools':[{'type':'namespace','name':'functions','tools':[{'type':'custom','name':'exec','description':description}]}]}
  body={'model':model,'stream':True,'store':False,'max_output_tokens':128,'reasoning':{'effort':'low'},'tools':[],'input':[
   {'role':'user','content':'Remember R2_FIX_918. Compute 137*29 using the tool.'},definition('Earlier guidance'),
   {'type':'custom_tool_call','name':'exec','call_id':'synthetic_history_1','input':'print(137*29)'},
   {'type':'custom_tool_call_output','call_id':'synthetic_history_1','output':'3973'},definition('Current guidance'),
   {'role':'user','content':'Do not call tools. Reply only the remembered code, a vertical bar, and the existing tool result.'}]}
  r={'model':model,'scope':'synthetic_route_adapter_tool_history','start':time.time()};text=[]
  try:
   url,payload,headers,adapt=route(body,{'Authorization':'Bearer bounded-regression-probe'},settings)
   r.update(output_cap=payload.get('max_output_tokens'),converted_call_name=next(i['name'] for i in payload['input'] if i.get('type')=='function_call'))
   with FreshProxyOpener(settings.get('upstream_proxy')).open(urllib.request.Request(url,data=json.dumps(payload).encode(),headers=headers),timeout=35) as response:
    r['http_status']=response.status
    for raw,event in adapted_stream(response,adapt):
     if event.get('type')=='response.output_text.delta':text.append(event.get('delta',''))
     if event.get('type') in {'response.completed','response.incomplete','response.failed'}:
      f=event.get('response',{});r.update(status=f.get('status'),usage=f.get('usage'),returned_model=f.get('model'))
   r['text']=''.join(text);r['strict_text_match']=r['text'].strip()=='R2_FIX_918|3973'
   r['passed']=r.get('status')=='completed' and r['strict_text_match']
   r['semantic_passed']=r.get('status')=='completed' and [x.strip() for x in r['text'].split('|')]==['R2_FIX_918','3973']
  except Exception as error:r.update(error=error_event(error,'regression'),passed=False)
  r['elapsed_ms']=round((time.time()-r['start'])*1000);out.append(r)
  Path(__file__).with_name('bounded-routing-r2-fix-probes.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(r),flush=True)
  if not r.get('usage'):break
if __name__=='__main__':main()
