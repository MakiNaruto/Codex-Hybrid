'use strict';
function createManagementControls(message){
  function el(tag, text, cls) { const node=document.createElement(tag); if(text!==undefined)node.textContent=text; if(cls)node.className=cls; return node; }
  // Keep native values and change handlers as the preference persistence boundary.
  function syncDesktopSelect(select){
    const trigger=select.parentElement.querySelector('.desktop-select-trigger');
    if(!trigger)return;
    trigger.textContent=select.selectedOptions[0].textContent;
    for(const option of select.parentElement.querySelectorAll('[role="option"]')){
      option.setAttribute('aria-selected',String(option.dataset.value===select.value));
    }
  }
  function initDesktopSelects(){
    let closeActive=()=>{};
    for(const select of document.querySelectorAll('.desktop-select select')){
      const wrapper=select.parentElement,label=document.querySelector('label[for="'+select.id+'"]');
      const trigger=el('button',undefined,'desktop-select-trigger'),list=el('div',undefined,'desktop-select-menu');
      trigger.type='button';trigger.id=select.id+'-trigger';
      label.id=select.id+'-label';label.htmlFor=trigger.id;
      trigger.setAttribute('aria-labelledby',label.id+' '+trigger.id);
      trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
      if(select.hasAttribute('aria-describedby'))trigger.setAttribute('aria-describedby',select.getAttribute('aria-describedby'));
      list.id=select.id+'-options';list.role='listbox';list.hidden=true;
      list.setAttribute('aria-labelledby',label.id);trigger.setAttribute('aria-controls',list.id);
      const close=()=>{list.hidden=true;trigger.setAttribute('aria-expanded','false');};
      const options=Array.from(select.options,option=>{
        const item=el('div',option.textContent,'desktop-select-option');
        item.role='option';item.tabIndex=-1;item.dataset.value=option.value;
        item.addEventListener('click',()=>{
          const changed=select.value!==option.value;
          select.value=option.value;syncDesktopSelect(select);close();trigger.focus();
          if(changed)select.dispatchEvent(new Event('change',{bubbles:true}));
        });
        list.append(item);return item;
      });
      const open=(index=select.selectedIndex)=>{
        closeActive();closeActive=close;list.hidden=false;trigger.setAttribute('aria-expanded','true');
        options[index].focus();
      };
      trigger.addEventListener('click',()=>list.hidden?open():close());
      trigger.addEventListener('keydown',event=>{
        if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
          event.preventDefault();open(event.key==='Home'?0:event.key==='End'?options.length-1:select.selectedIndex);
        }
      });
      list.addEventListener('keydown',event=>{
        const index=options.indexOf(document.activeElement);
        if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
          event.preventDefault();options[event.key==='Home'?0:event.key==='End'?options.length-1:(index+(event.key==='ArrowDown'?1:-1)+options.length)%options.length].focus();
        }else if(event.key==='Enter'||event.key===' '){event.preventDefault();options[index]?.click();}
        else if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();trigger.focus();}
        else if(event.key==='Tab')close();
      });
      wrapper.addEventListener('focusout',event=>{if(!wrapper.contains(event.relatedTarget))close();});
      document.addEventListener('pointerdown',event=>{if(!wrapper.contains(event.target))close();});
      wrapper.closest('details').addEventListener('toggle',event=>{if(!event.target.open)close();});
      select.hidden=true;wrapper.append(trigger,list);wrapper.classList.add('is-enhanced');syncDesktopSelect(select);
    }
  }
  async function copyText(value){
    try{
      await navigator.clipboard.writeText(value);
      message('已复制到剪贴板。');return;
    }catch(error){/* Some browsers deny or do not expose the Clipboard API. */}
    const previousFocus=document.activeElement;
    const input=el('textarea');input.value=value;input.readOnly=true;input.className='clipboard-fallback';
    document.body.append(input);
    let copied=false;
    try{
      input.focus();input.select();input.setSelectionRange(0,input.value.length);
      copied=document.execCommand('copy');
    }catch(error){/* Offer manual copying if the compatibility path is also blocked. */}
    finally{input.remove();previousFocus?.focus({preventScroll:true});}
    if(copied)message('已复制到剪贴板。');
    else{
      message('无法自动复制，请在弹出的文本框中手动复制模型 key。',true);
      window.prompt('请复制模型 key（Ctrl+C / ⌘C）：',value);
    }
  }
  let fieldId=0;
  function help(text, title='查看说明'){
    const trigger=el('button','?','help-trigger');
    trigger.type='button';trigger.dataset.help=text;trigger.setAttribute('aria-label',title);
    trigger.setAttribute('aria-expanded','false');return trigger;
  }
  function field(title,value='',type='text',description=''){
    const wrapper=el('div',undefined,'form-field');
    const caption=el('div',undefined,'field-caption');
    const label=el('label',title),input=el('input');
    input.id='field-'+(++fieldId);label.htmlFor=input.id;input.type=type;
    if(type==='checkbox')input.checked=value;else input.value=value;
    if(type==='checkbox'){label.className='check';label.append(input);wrapper.append(label);}
    else{caption.append(label);if(description)caption.append(help(description,title+'说明'));wrapper.append(caption,input);}
    return {label:wrapper,input};
  }
  let helpPanel;
  let closeHelp=()=>{};
  function initHelp(){
    helpPanel=el('div',undefined,'help-panel');
    helpPanel.id='help-panel';helpPanel.role='tooltip';helpPanel.hidden=true;document.body.append(helpPanel);
    let activeHelp=null,helpPinned=false,helpTimer;
    closeHelp=function(){
      clearTimeout(helpTimer);
      if(activeHelp){activeHelp.removeAttribute('aria-describedby');activeHelp.setAttribute('aria-expanded','false');}
      activeHelp=null;helpPinned=false;helpPanel.hidden=true;
    }
    function positionHelp(){
      if(!activeHelp?.isConnected){closeHelp();return;}
      const rect=activeHelp.getBoundingClientRect(),box=helpPanel.getBoundingClientRect();
      const left=Math.max(12,Math.min(rect.left+rect.width/2-box.width/2,innerWidth-box.width-12));
      const below=rect.bottom+9;
      helpPanel.style.left=left+'px';helpPanel.style.top=Math.max(12,below+box.height<innerHeight-12?below:rect.top-box.height-9)+'px';
    }
    function openHelp(trigger){
      clearTimeout(helpTimer);
      if(activeHelp!==trigger){closeHelp();activeHelp=trigger;}
      const helpHost=trigger.closest('dialog')||document.body;
      if(helpPanel.parentElement!==helpHost)helpHost.append(helpPanel);
      trigger.setAttribute('aria-describedby',helpPanel.id);trigger.setAttribute('aria-expanded','true');
      helpPanel.dataset.tone=trigger.dataset.helpTone||'neutral';
      helpPanel.replaceChildren();
      if(trigger.dataset.helpTitle)helpPanel.append(el('strong',trigger.dataset.helpTitle,'help-panel-title'));
      helpPanel.append(el('span',trigger.dataset.help));helpPanel.hidden=false;positionHelp();
    }
    function delayCloseHelp(){if(!helpPinned)helpTimer=setTimeout(closeHelp,180);}
     document.addEventListener('pointerover',event=>{const trigger=event.target.closest('.help-trigger');if(trigger&&(!helpPinned||trigger===activeHelp))openHelp(trigger);});
     document.addEventListener('pointerout',event=>{if(event.target.closest('.help-trigger')&&!event.relatedTarget?.closest('.help-trigger'))delayCloseHelp();});
     document.addEventListener('focusin',event=>{const trigger=event.target.closest('.help-trigger');if(trigger)openHelp(trigger);else if(!helpPinned)closeHelp();});
     document.addEventListener('focusout',event=>{if(event.target.closest('.help-trigger'))delayCloseHelp();});
     document.addEventListener('click',event=>{
       const trigger=event.target.closest('.help-trigger');
       if(trigger){event.preventDefault();if(activeHelp===trigger&&helpPinned)closeHelp();else{openHelp(trigger);helpPinned=true;}}
       else if(!helpPanel.contains(event.target))closeHelp();
     });
     document.addEventListener('keydown',event=>{if(event.key==='Escape')closeHelp();});
     document.addEventListener('close',event=>{if(event.target.contains(activeHelp))closeHelp();},true);
     helpPanel.addEventListener('pointerenter',()=>clearTimeout(helpTimer));helpPanel.addEventListener('pointerleave',delayCloseHelp);
     window.addEventListener('resize',()=>{if(activeHelp)positionHelp();});
     window.addEventListener('scroll',()=>{if(activeHelp)positionHelp();},true);
  }
  return {el,help,field,copyText,syncDesktopSelect,initDesktopSelects,initHelp,closeHelp:()=>closeHelp()};
}
