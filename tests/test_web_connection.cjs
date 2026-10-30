const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('src/management/web/app.js','utf8');
const testCode=source.slice(source.indexOf('const connectionResults='),source.indexOf('function modelEditor'));

test('CC connection tests use source availability independently of list membership',()=>{
  const context=vm.createContext({
    el:()=>({append(){}}),button:()=>({}),
  });
  vm.runInContext(testCode,context);
  for(const enabled of [false,true]){
    const model={key:'vendor/model',enabled,source_enabled:true};
    // Capture the button appended to its wrapper.
    context.el=()=>({append(button){this.button=button;}});
    assert.equal(context.testButton(model,true).button.disabled,false);
    assert.equal(context.testButton(model).button.disabled,!enabled);
  }
  assert.equal(context.testButton({enabled:true,source_enabled:false},true).button.disabled,true);
  assert.equal(context.testButton(undefined,true).button.disabled,true);
});
