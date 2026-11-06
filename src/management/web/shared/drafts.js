'use strict';
function createProviderDrafts(providers,status,el){
  function dirtyCards(){return [...providers.children].filter(card=>card.dataset.dirty==='true');}
  function updateUnsaved(){
    const count=dirtyCards().length;
    status.textContent=count?'有 '+count+' 个厂商尚未保存，刷新或离开前请保存':'';
  }
  function markDirty(card){
    if(!card)return;card.dataset.dirty='true';
    if(!card.querySelector('.dirty-badge'))card.querySelector('.provider-heading').append(el('span','未保存','dirty-badge'));
    updateUnsaved();
  }
  function clearDirty(card){card.dataset.dirty='false';card.querySelector('.dirty-badge')?.remove();updateUnsaved();}
  function discardDrafts(){
    if(dirtyCards().length&&!confirm('有尚未保存的厂商修改，确定放弃这些修改并重新读取？'))return false;
    for(const card of dirtyCards())clearDirty(card);return true;
  }
  function installUnloadGuard(){
    window.addEventListener('beforeunload',event=>{if(dirtyCards().length){event.preventDefault();event.returnValue='';}});
  }
  return {dirtyCards,updateUnsaved,markDirty,clearDirty,discardDrafts,installUnloadGuard};
}
