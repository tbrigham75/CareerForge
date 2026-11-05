(() => {
 const root=document.querySelector('#ai-review'); if(!root)return;
 const $=id=>document.getElementById(id), fields=['action','metric','impact'];
 let draft=null,current={},dirty=false,busy=false;
 const say=t=>{$('ai-status').textContent=t;};
 function element(tag,text){const e=document.createElement(tag);if(text)e.textContent=text;return e;}
 function collect(){return {suggestions:Object.fromEntries(fields.map(f=>[f,$('ai-text-'+f)?.value||''])),selected:fields.filter(f=>$('ai-check-'+f)?.checked),dismissed:fields.filter(f=>$('ai-dismiss-'+f)?.checked),pending_answers:Object.fromEntries(fields.map(f=>[f,$('ai-answer-'+f)?.value||'']))};}
 function count(){const n=collect().selected.filter(f=>$('ai-text-'+f).value.trim()&&$('ai-text-'+f).value!==current[f]).length;$('ai-apply').textContent=`Save Selected Changes (${n})`;$('ai-apply').disabled=!n||busy;}
 async function call(operation,extra={}){
  const response=await fetch(`/accomplishments/${root.dataset.record}/ai-review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf:root.dataset.csrf,operation,draft_id:draft?.id,provider_id:$('ai-provider').value,include_context:$('ai-context').checked,...extra})});
  if(!response.headers.get('content-type')?.includes('application/json'))throw Error('Session expired. Copy your unsaved text before signing in again.');
  const data=await response.json();if(!response.ok)throw Error(data.detail||'Request failed. Your text is preserved.');
  if(data.confirmation_required){if(!confirm('Send this content to the selected remote provider?\n'+JSON.stringify(data.transmission,null,2)))throw Error('Canceled.');return call(operation,{...extra,remote_confirmation:true});}return data;
 }
 async function run(fn){if(busy)return;busy=true;root.querySelectorAll('button,input,textarea,select').forEach(e=>e.disabled=true);say('Working…');try{await fn();}catch(e){say(e.message);}finally{busy=false;root.querySelectorAll('button,input,textarea,select').forEach(e=>e.disabled=false);count();}}
 function render(){
  $('ai-fields').replaceChildren();if(!draft)return;
  $('ai-context').checked=!!draft.content.include_context; if(draft.content.provider_id)$('ai-provider').value=draft.content.provider_id;
  for(const f of fields){const card=element('section');card.className='panel';card.append(element('h3',f[0].toUpperCase()+f.slice(1)));const grid=element('div');grid.className='grid';const old=element('div');old.append(element('strong','Current'),element('p',current[f]||'Not provided'));const label=element('label','Suggested');const text=element('textarea');text.id='ai-text-'+f;text.value=draft.content.suggestions[f]||'';label.append(text);grid.append(old,label);card.append(grid);
   const use=element('label','Use this suggestion '),check=element('input');check.type='checkbox';check.id='ai-check-'+f;check.checked=(draft.content.selected||[]).includes(f)&&!!text.value;use.append(check);card.append(use);
   const based=element('details');based.append(element('summary','Based on…'),element('p','Review against the original note and your answers; this is context, not a verified citation.'),element('pre',(draft.content.sources?.[f]||[]).join('\n')||'No matching source excerpt. Check this suggestion carefully against the original note.'));if(draft.content.answers[f])based.append(element('p',draft.content.answers[f]));card.append(based);
   const question=element('p',draft.content.questions[f]||'Add a fact or clarification to refine this field.');card.append(question);
   const answer=element('textarea');answer.id='ai-answer-'+f;answer.setAttribute('aria-label',f+' follow-up answer');answer.value=draft.content.pending_answers?.[f]||'';card.append(answer);
   if(f==='metric'||f==='impact'){
    const ideas=element('section');ideas.append(element('h4',f==='metric'?'Metric starting points':'Impact starting points'),element('p','Ideas based on your raw note. Choose one, edit it to fit your experience, and replace or remove any bracketed placeholders before applying.'));
    for(const idea of draft.content[f+'_suggestions']||[]){
     const item=element('div');item.append(element('p',idea));const choose=element('button','Use as starting point');choose.type='button';choose.onclick=()=>{if(text.value.trim()&&dirty&&!confirm('Replace this draft suggestion with the selected starting point?'))return;text.value=idea;check.checked=false;dismiss.checked=false;question.hidden=false;answer.hidden=false;refine.hidden=false;dirty=true;count();text.focus();say('Starting point added. Edit it, then select Use this suggestion when ready.');};item.append(choose);ideas.append(item);
    }card.append(ideas);
   }
   const skip=element('label',"I don’t know / Leave blank "),dismiss=element('input');dismiss.type='checkbox';dismiss.id='ai-dismiss-'+f;dismiss.checked=(draft.content.dismissed||[]).includes(f);skip.append(dismiss);card.append(skip);
   const refine=element('button','Update '+f);refine.type='button';refine.onclick=()=>run(async()=>{const state=collect();if(!state.pending_answers[f].trim())throw Error('Enter an answer first.');const result=await call('refine',{...state,field:f,answer:state.pending_answers[f]});draft=result;draft.content.pending_answers=state.pending_answers;draft.content.dismissed=state.dismissed;render();dirty=true;say('Suggestion updated. Review before saving.');});card.append(refine);
   const regen=element('button','Regenerate '+f);regen.type='button';regen.onclick=()=>run(async()=>{if(dirty&&!confirm('Replace this field’s suggestion? Other edits are kept.'))return;const state=collect();draft=await call('refine',{...state,field:f});draft.content.pending_answers=state.pending_answers;draft.content.dismissed=state.dismissed;render();dirty=true;say('Suggestion regenerated.');});card.append(regen);
   function dismissQuestion(){question.hidden=dismiss.checked;answer.hidden=dismiss.checked;refine.hidden=dismiss.checked;}
   dismiss.onchange=()=>{dismissQuestion();if(dismiss.checked){text.value='';check.checked=false;}dirty=true;count();};dismissQuestion();$('ai-fields').append(card);
  }count();
 }
 async function load(){const data=await call('load');current=data.current;for(const f of fields){if($('saved-'+f))$('saved-'+f).textContent=current[f]||'[Not provided]';}$('ai-provider').replaceChildren();for(const p of data.providers){const o=element('option',p.name+' — '+p.model);o.value=p.id;$('ai-provider').append(o);}if(!data.providers.length)say('Configure an AI provider in Settings → AI Providers.');$('ai-resume').replaceChildren();for(const d of data.drafts){const b=element('button',d.status==='accepted'?'Undo These Changes':'Resume AI Draft');b.type='button';b.onclick=()=>run(async()=>{if(dirty&&!confirm('Leave your unsaved draft edits?'))return;draft=d;if(d.status==='accepted'){const result=await call('undo');dirty=false;await load();draft=null;$('ai-fields').replaceChildren();say(result.message);}else{render();dirty=false;say('Draft resumed.');}});$('ai-resume').append(b);}}
 $('ai-open').onclick=()=>run(async()=>{$('ai-panel').hidden=false;await load();});
 $('ai-generate').onclick=()=>run(async()=>{if(dirty&&!confirm('Generate a new draft without saving these edits?'))return;draft=await call('generate');render();dirty=false;say('Suggestions ready. Review every claim.');});
 $('ai-save-draft').onclick=()=>run(async()=>{if(!draft)throw Error('Generate or resume a draft first.');await call('save_draft',collect());dirty=false;say('AI draft saved. Accomplishment unchanged.');});
 $('ai-apply').onclick=()=>run(async()=>{const result=await call('apply',collect());dirty=false;current=result.current||current;await load();$('ai-fields').replaceChildren();draft=null;const missing=fields.filter(f=>!current[f]);say('Selected changes saved.'+(missing.length?' Still blank: '+missing.join(', ')+'.':'' ));});
 $('ai-discard').onclick=()=>run(async()=>{if(!draft)return;if(!confirm('Discard this AI draft?'))return;await call('discard');draft=null;dirty=false;$('ai-fields').replaceChildren();await load();say('Draft discarded.');});
 document.querySelectorAll('[data-ai-undo]').forEach(button=>button.onclick=()=>run(async()=>{if(dirty&&!confirm('Leave unsaved draft edits?'))return;draft={id:button.dataset.aiUndo};const result=await call('undo');dirty=false;draft=null;$('ai-panel').hidden=false;await load();$('ai-fields').replaceChildren();button.disabled=true;say(result.message);}));
 root.addEventListener('input',()=>{dirty=true;count();});window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
})();