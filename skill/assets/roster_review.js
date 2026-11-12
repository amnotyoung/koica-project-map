// Preserve source titles and date fields. Only a reviewer decision changes the period.
const titleYears=/[(（]\s*['‘’`]?((?:20)?\d{2})\s*[-–—~]\s*['‘’`]?((?:20)?\d{2})\s*[/／)）]/;
function periodOptions(row){
 const m=(row.name_ko||'').match(titleYears), full=v=>v.length===2?'20'+v:v;
 const named=m?full(m[1])+'-'+full(m[2]):'';
 const decision=row._editor_period;
 const source=decision?.title===named?decision.source:row._period||'';
 return {source,named};
}
function periodControl(row){
 const {source,named}=periodOptions(row);
 if(!named||named===source)return '';
 const choice=row._editor_period?.title===named?row._editor_period.choice:'';
 const option=(key,text)=>`<option value="${key}" ${choice===key?'selected':''}>${esc(text)}</option>`;
 return `<label class="period-review">사업기간 불일치 · ${esc(source||'기간 미등록')} / ${esc(named)}
 <select data-period aria-label="지도에 쓸 사업기간">${option('','기존 값 유지 · 미결정')}
 ${source?option('source','기간 필드 '+source):''}${option('title','사업명 '+named)}</select></label>`;
}
function choosePeriod(row,choice){
 const {source,named}=periodOptions(row);
 if(!named)return;
 if(choice){row._editor_period={source,title:named,choice};row._period=choice==='title'?named:source}
 else{row._period=source;delete row._editor_period}
}
function similarTarget(row){
 return rows.find(r=>!r._notice_candidate && r.id && r.id===(row._linked_project_id||row._similar_project_id));
}
function duplicateControl(row){
 const other=similarTarget(row);if(!other)return '';
 const linked=row._duplicate_decision==='linked',separate=row._duplicate_decision==='separate';
 function side(item,heading){
  const link=webUrl(item._source_info?.url||item.scope_sources?.[0]);
  return `<div><b>${heading}</b><p>${esc(item.name_ko)}</p><small>${esc([item._period,item.place,item._stage].filter(Boolean).join(' · '))}</small>
   ${link?`<a href="${esc(link)}" target="_blank" rel="noopener noreferrer">원문 ↗</a>`:''}</div>`;
 }
 return `<details class="duplicate"><summary>${linked?'동일 사업으로 연결됨':separate?'별도 사업으로 유지 중':'유사 사업 비교'}</summary>
 <div class="compare">${side(other,'기존 사업')}${side(row,'공고 후보')}</div>
 <button data-duplicate="linked" aria-pressed="${linked}">동일 사업 연결</button>
 <button data-duplicate="separate" aria-pressed="${separate}">별도 사업 유지</button>
 ${linked?`<small>기존 사업 ${other.selected?'포함':'제외'} · 공고는 근거로 연결</small>`:''}</details>`;
}
function decideDuplicate(row,choice){
 const target=similarTarget(row);if(!target)return;
 row._duplicate_decision=choice;
 if(choice==='linked'){
  if(row.selected)target.selected=true;
  row._linked_project_id=target.id;row.selected=false;
 }else delete row._linked_project_id;
 draw();
}
function attachLinkedNotices(records){
 const sources=new Map();
 const candidateIds=new Set(records.filter(p=>p._notice_candidate).map(p=>p.id));
 for(const p of records){
  if(p._duplicate_decision!=='linked'||!p._linked_project_id)continue;
  const items=sources.get(p._linked_project_id)||[];
  items.push({id:p.id,title:p._notice_title||p.name_ko,urls:p.scope_sources||[]});sources.set(p._linked_project_id,items);
 }
 for(const p of records){
  const retained=(p._linked_notices||[]).filter(n=>!candidateIds.has(n.id));
  const linked=[...retained,...(sources.get(p.id)||[])];
  if(linked.length)p._linked_notices=linked;
  else delete p._linked_notices;
 }
}
function showName(key,label,row){
 const value=row[key]||'';
 if(!value.trim()||row._editingNames?.has(key))return `<label class="caption">${label}<textarea rows="2" data-field="${key}">${esc(value)}</textarea></label>
  ${value?`<button type="button" data-name-done="${key}">완료</button>`:''}`;
 return `<button class="name-read" type="button" data-edit-name="${key}" aria-label="${esc(label+' 수정: '+value)}"><span>${esc(value)}</span><small>수정</small></button>`;
}
