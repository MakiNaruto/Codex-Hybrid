'use strict';
// The browser keeps its authenticated HTTP adapter. Packaged pages use private IPC.
window.hybridDesktop = (() => {
  const native=window.__TAURI__;
  if(!native?.core?.invoke)return null;
  let pendingWrites=0;
  async function request(request){
    let response;
    try{response=await native.core.invoke('desktop_manage',{request});}
    catch{throw Error('SERVICE_UNREACHABLE');}
    if(!response||typeof response.ok!=='boolean')throw Error('INVALID_SERVICE_RESPONSE');
    if(!response.ok)throw Error(response.error||'OPERATION_FAILED');
    return response.result;
  }
  return {
    request,
    get pendingWrites(){return pendingWrites;},
    async api(path,body){
      const write=body!==undefined;
      if(write)pendingWrites++;
      try{return await request({action:'web_api',path,method:write?'POST':'GET',body:write?body:null});}
      finally{if(write)pendingWrites--;}
    }
  };
})();
// The packaged window is 900x640; browser pages keep the roomier spacing.
if(window.hybridDesktop&&window.document?.documentElement)window.document.documentElement.classList.add('desktop-shell');
