// The country outline, GeoNames index and both boundary layers travel with the HTML.
const geo = JSON.parse(document.getElementById('geo-data').textContent);
const modes = {external:'겸임국',unknown:'위치 미확인',site:'핀', admin1:'주 권역', admin2:'군 권역', nationwide:'전국'};
let currentLocation = null, locationView = [0,0,640,320], activePin = 0, gesture = null;
const normPlace = s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').normalize('NFC').toLowerCase().replace(/[\s'’.·_-]/g,'');
function soundKey(s){
 const initials='g kk n d tt r m b pp s ss _ j jj ch k t p h'.split(' ');
 const vowels='a ae ya yae eo e yeo ye o wa wae oe yo u wo we wi yu eu ui i'.split(' ');
 const ends='_ k k k n n n t l k m l l l p l m p p t t ng t t k t p t'.split(' ');
 s=s.replace(/[가-힣]/g,c=>{let n=c.charCodeAt(0)-44032;return initials[Math.floor(n/588)]+vowels[Math.floor(n%588/28)]+ends[n%28]});
 return normPlace(s).replace(/[^a-z]/g,'').replace(/eu/g,'').replace(/l/g,'r').replace(/(.)\1+/g,'$1').replace(/[aeiou]+$/,'');
}
const lookupNames=c=>[c.name,...(c.alt||[])];
const cityIndex=(geo.cities||[]).map(c=>({city:c,names:lookupNames(c).map(normPlace),sounds:lookupNames(c).map(soundKey)}));
function cityMatch(term){
 const name=normPlace(term),sound=soundKey(term);
 if(!name)return null;
 const exact=cityIndex.filter(c=>c.names.includes(name));
 const matches=exact.length?exact:cityIndex.filter(c=>sound.length>=3&&c.sounds.includes(sound));
 return matches.length===1?matches[0].city:null;
}
const asLon=lon=>((lon+180)%360+360)%360-180;
function mapXY(lon,lat){
 const [s,x,y,mid]=geo.transform;
 return [x+(lon+360*Math.round((mid-lon)/360))*s,y-Math.asinh(Math.tan(Math.max(-85,Math.min(85,lat))*Math.PI/180))*180/Math.PI*s];
}
function mapCoord(x,y){
 const [s,tx,ty]=geo.transform;
 return {lon:+asLon((x-tx)/s).toFixed(6),lat:+(Math.atan(Math.sinh((ty-y)/s*Math.PI/180))*180/Math.PI).toFixed(6)};
}
function findArea(term,mode){
 const text=term.trim().replace(/\s*(?:주|도|군|구)$/,'');
 if(!text)return null;
 const options=geo.regions[mode]||[];
 const same=options.filter(f=>normPlace(f.name)===normPlace(text));
 const hits=same.length?same:options.filter(f=>soundKey(f.name)===soundKey(text));
 return hits.length===1?hits[0]:null;
}
function pinsFromText(text, previous=[]){
 return text.split('/').map(s=>s.trim()).filter(Boolean).map(name=>{
  const kept=previous.find(p=>normPlace(p.query||p.name)===normPlace(name));
  if(kept && hasPin(kept))return {...kept};
  const city=cityMatch(name);
  return city?{query:name,name:city.name,lon:+asLon(city.lon).toFixed(6),lat:city.lat,source:'GeoNames'}:{name};
 });
}
function existingPins(row){
 if(row.reviewed_pins)return [...row.reviewed_pins,...(row.reviewed_unresolved||[]).map(name=>({name}))].map(p=>({...p}));
 if(['external','unknown','nationwide'].includes(row.coverage))return [];
 if(row.sites)return row.sites.flatMap(existingPins);
 const coord=row.geonames_locality||row.source_coord;
 if(coord&&Number.isFinite(coord.lon)&&Number.isFinite(coord.lat))return [{name:coord.name||row.place,lon:coord.lon,lat:coord.lat,source:coord.source||'GeoNames'}];

 return pinsFromText(row.place||'');
}
function initialGeo(row){
 const mode=modes[row.coverage]?row.coverage:'site';
 const regions=geo.regions?.[mode]||[];
 const oldNames=row[mode+'_names']||[row[mode+'_name']];
 const ids=row[mode+'_ids']||regions.filter(f=>oldNames.some(n=>n&&normPlace(n)===normPlace(f.name.replace(/\s+(Region|Province|District|County)$/i,'')))).map(f=>f.id);
 return {mode,place:row.place||'',evidence:row._location_evidence||'',pins:mode==='site'?existingPins(row):[],ids:[...ids]};
}
// Only confirmed values live in the roster. Switching rows or filters keeps each draft.
const geoSessions=new WeakMap(), geoUndo=new WeakMap();
const placeKey=s=>(s||'').normalize('NFC').replace(/\s+/g,'');
const hasPin=p=>Number.isFinite(p.lon)&&Number.isFinite(p.lat);
function session(row){
 if(!geoSessions.has(row)){
  const original=initialGeo(row);
  geoSessions.set(row,{original,mode:original.mode,byMode:{[original.mode]:structuredClone(original)}});
 }
 return geoSessions.get(row);
}
function geoState(row=currentLocation){
 const draft=geoSessions.get(row);
 return draft?draft.byMode[draft.mode]:initialGeo(row);
}
function editGeo(){const d=session(currentLocation);return d.byMode[d.mode]}
function pendingGeo(row){
 const d=geoSessions.get(row);
 return !!d && JSON.stringify(d.original)!==JSON.stringify(d.byMode[d.mode]);
}
function placeField(row){return document.querySelector(`article[data-key="${row._key}"] [data-field=place]`)}
function setPlace(label){editGeo().place=label;placeField(currentLocation).value=label}
function activateLocation(row,text){
 if(!row)return;
 const changed=currentLocation!==row;
 if(changed){currentLocation=row;activePin=0;locationView=[0,0,640,320]}
 const article=document.querySelector(`article[data-key="${row._key}"]`);
 if(!article)return;
 article.append($('location-panel'));$('location-panel').hidden=false;
 if(typeof text==='string' && placeKey(text)!==placeKey(geoState(row).place)){
  const d=session(row),query=text.trim();
  if(placeKey(query)===placeKey(d.original.place)){
   d.mode=d.original.mode;d.byMode[d.mode]=structuredClone(d.original);
  }else{
   const national=['전국','전역',data.country+'전국',data.country+'전역'].includes(placeKey(query));
   const level=/주$|도$/.test(query)?'admin1':/군$|구$/.test(query)?'admin2':d.mode.startsWith('admin')?d.mode:null;
   const mode=national?'nationwide':level||'site', terms=query.split('/').map(t=>t.trim()).filter(Boolean);
   const areas=level&&geo.transform?terms.map(t=>findArea(t,level)):[];
   const pins=mode==='site'?pinsFromText(query,d.byMode.site?.pins):[];
   d.byMode[mode]={mode,place:query,evidence:'',pins,ids:areas.every(Boolean)?[...new Set(areas.map(a=>a.id))]:[]};d.mode=mode;
   activePin=Math.max(0,pins.findIndex(p=>!hasPin(p)));
   const term=normPlace(terms.at(-1)||'');
   $('geo-citylist').innerHTML=(term&&terms.length===1?cityIndex.filter(c=>c.names.some(n=>n.startsWith(term))):[])
    .slice(0,12).map(c=>`<option value="${esc(c.city.name)}"></option>`).join('');
  }
 }
 if(changed || typeof text==='string')$('region-filter').value='';
 renderLocation();
}
const geoFields=['place','sites','source_coord','geonames_locality','aliases','kind','place_en','admin1_ids','admin2_ids',
 'admin1_names','admin2_names','admin1_name','admin2_name','scope_label','scope_label_en','_coord_source','_inferred_scope',
 'reviewed_pins','reviewed_unresolved','coverage','_location_basis','_location_evidence'];
function syncLocationPanel(){
 placeField(currentLocation).value=geoState().place;
 renderLocation();
}
$('geo-confirm').onclick=()=>{
 if(!currentLocation||!pendingGeo(currentLocation))return;
 const row=currentLocation,state=geoState();
 geoUndo.set(row,Object.fromEntries(geoFields.filter(k=>k in row).map(k=>[k,structuredClone(row[k])])));
 const keepEnglish=placeKey(row.place)===placeKey(state.place)?row.place_en:undefined;
 row.place=state.place.trim();
 applyLocation(row,state);
 if(keepEnglish!==undefined)row.place_en=keepEnglish;
 geoSessions.delete(row);activePin=0;syncLocationPanel();
};
$('geo-cancel').onclick=()=>{geoSessions.delete(currentLocation);activePin=0;syncLocationPanel()};
$('geo-undo').onclick=()=>{
 const snapshot=geoUndo.get(currentLocation);if(!snapshot)return;
 for(const k of geoFields)delete currentLocation[k];
 Object.assign(currentLocation,snapshot);geoSessions.delete(currentLocation);geoUndo.delete(currentLocation);
 activePin=0;syncLocationPanel();
};
function locationBasis(row,pin){
 if(pendingGeo(row))return '미확정 변경';
 if(row._location_basis==='group-representative')return '그룹 대표 위치 · 사업지 미검증';
 if(row._location_basis==='manager-reviewed')return '담당자 확정';
 if(row._location_basis==='public-project-evidence')return '공개 사업자료 기준';
 return pin?'지명 기준 · 사업지 미검증':'사업지 미확인';
}
function renderLocation(){
 const state=geoState(),mode=state.mode,regions=geo.regions?.[mode]||[],area=mode.startsWith('admin');
 const dirty=pendingGeo(currentLocation);
 $('geo-confirm').disabled=!dirty;$('geo-cancel').disabled=!geoSessions.has(currentLocation);$('geo-undo').disabled=!geoUndo.has(currentLocation);
 $('geo-basis').textContent=locationBasis(currentLocation,state.pins[activePin]);
 $('geo-evidence').value=state.evidence||'';
 const links=currentLocation._location_basis==='public-project-evidence'&&!dirty?currentLocation.scope_sources||[]:[];
 $('geo-links').innerHTML=links.map(webUrl).filter(Boolean).map((url,i)=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">근거 ${i+1} ↗</a>`).join(' ');
 $('location-controls').hidden=!geo.transform;
 if(!geo.transform){$('geo-status').textContent='지도 자료 없음';return}
 $('geo-mode').value=mode;$('area-controls').hidden=!area;$('pin-controls').hidden=mode!=='site';
 const label=geo.years?.[mode];$('geo-year').textContent=area&&label?`geoBoundaries · ${label}년 기준`:'';
 const nameCounts=new Map();for(const region of regions)nameCounts.set(region.name,(nameCounts.get(region.name)||0)+1);
 const filtered=regions.filter(f=>normPlace(f.name).includes(normPlace($('region-filter').value)));
 $('region-options').innerHTML=filtered.map(f=>`<option value="${esc(f.id)}">${state.ids.includes(f.id)?'✓ ':''}${esc(f.name)}${nameCounts.get(f.name)>1?' · '+esc(f.id):''}</option>`).join('');
 $('region-options').value='';
 const svg=$('geo-map');svg.setAttribute('viewBox',locationView.join(' '));
 const outlines=area?regions:geo.regions.admin1;
 const paths=outlines.map(f=>`<path d="${f.path}" fill-rule="evenodd" class="boundary${area?' selectable':''}${area&&state.ids.includes(f.id)?' chosen':''}" data-region="${esc(f.id)}"><title>${esc(f.name)}</title></path>`).join('');
 const size=locationView[2]/640;
 const cities=geo.cities.slice(0,10).map(c=>{const [x,y]=mapXY(c.lon,c.lat);return `<g pointer-events="none"><circle cx="${x}" cy="${y}" r="${1.7*size}" fill="#4e6870"/><text x="${x+3*size}" y="${y-3*size}" font-size="${8*size}">${esc(c.name)}</text></g>`}).join('');
 const pins=mode==='site'?state.pins.filter(hasPin):[];
 const marks=state.pins.map((p,i)=>{
  if(mode!=='site'||!hasPin(p))return '';
  const [x,y]=mapXY(p.lon,p.lat);
  return `<g class="pin ${currentLocation._location_basis==='group-representative'&&!dirty?'representative':''}" data-pin="${i}" transform="translate(${x} ${y}) scale(${size})"><circle r="11" fill="transparent"/><circle r="6" fill="${pins.length>1?'white':'#c33936'}" stroke="${pins.length>1?'#39855a':'white'}" stroke-width="2.4"/><title>${esc(p.name)} · 드래그하여 이동</title></g>`;
 }).join('');
 svg.innerHTML=`<path d="${geo.land}" fill="#fafaf5" stroke="#78908e" vector-effect="non-scaling-stroke" fill-rule="evenodd"/>${paths}${cities}${marks}`;
 $('pin-select').innerHTML=state.pins.map((p,i)=>`<option value="${i}">${esc(p.name)}${hasPin(p)?'':' · 위치 지정'}</option>`).join('');$('pin-select').value=String(activePin);
 const p=state.pins[activePin];
 $('latitude').value=p&&hasPin(p)?p.lat:'';$('longitude').value=p&&hasPin(p)?p.lon:'';
 $('coord-error').textContent='';
 $('pin-coord').textContent=p&&hasPin(p)?`좌표 출처 · ${p.source||'미기재'}`:'';
 $('geo-status').textContent=area?(state.ids.length?regions.filter(f=>state.ids.includes(f.id)).map(f=>f.name).join(' · '):regions.length?'지도나 목록에서 대상 권역을 선택하세요.':'이 단계의 공개 경계가 없습니다.')
  :mode==='nationwide'?'전국 사업으로 표시합니다.':state.pins.some(p=>!hasPin(p))?'찾지 못한 지명을 선택한 뒤 지도에서 위치를 찍으세요.':'핀을 끌거나 지도를 클릭해 위치를 지정하세요.';
}
$('geo-evidence').oninput=e=>{
 editGeo().evidence=e.target.value;
 $('geo-confirm').disabled=!pendingGeo(currentLocation);$('geo-cancel').disabled=false;
};
function toggleArea(id){
 if(!id)return;
 const state=editGeo();state.ids=state.ids.includes(id)?state.ids.filter(item=>item!==id):[...state.ids,id];
 setPlace(geo.regions[state.mode].filter(f=>state.ids.includes(f.id)).map(f=>f.name).join(' · '));renderLocation();
}
function svgPoint(e){
 const svg=$('geo-map');return new DOMPoint(e.clientX,e.clientY).matrixTransform(svg.getScreenCTM().inverse());
}
function assignPin(coord){
 const state=editGeo();
 if(!state.pins.length){state.pins.push({name:state.place.trim()||'지정 위치'});activePin=0}
 if(state.pins[activePin].lat===coord.lat && state.pins[activePin].lon===coord.lon)return;
 Object.assign(state.pins[activePin],coord,{source:'담당자 지정'});
 if(!state.place.trim())setPlace(state.pins[activePin].name);
 renderLocation();
}
function placePin(point){assignPin(mapCoord(point.x,point.y))}
$('coord-apply').onclick=()=>{
 const lat=$('latitude').valueAsNumber,lon=$('longitude').valueAsNumber;
 if(!Number.isFinite(lat)||Math.abs(lat)>90||!Number.isFinite(lon)||Math.abs(lon)>180){
  $('coord-error').textContent='위도 −90~90, 경도 −180~180을 입력하세요.';return;
 }
 assignPin({lat,lon});
};
function changeZoom(ratio){
 const [x,y,w,h]=locationView, newW=Math.max(5,Math.min(640,w*ratio)),newH=newW/2;
 const p=geoState().pins[activePin], center=p&&hasPin(p)?mapXY(p.lon,p.lat):[x+w/2,y+h/2];
 locationView=newW===640?[0,0,640,320]:[center[0]-newW/2,center[1]-newH/2,newW,newH];renderLocation();
}
$('geo-mode').onchange=e=>{
 const d=session(currentLocation), mode=e.target.value, query=geoState().place;
 if(!d.byMode[mode]){
  const area=mode.startsWith('admin')?findArea(query,mode):null;
  d.byMode[mode]={mode,evidence:'',ids:area?[area.id]:[],pins:mode==='site'?pinsFromText(query):[],
   place:mode==='nationwide'?data.country+' 전역':area?area.name:mode==='site'?query:''};
 }
 d.mode=mode;activePin=0;$('region-filter').value='';syncLocationPanel();
};
$('region-filter').oninput=renderLocation;
$('region-options').onchange=e=>toggleArea(e.target.value);
$('pin-select').onchange=e=>{activePin=Number(e.target.value);renderLocation()};
$('geo-plus').onclick=()=>changeZoom(.5);$('geo-minus').onclick=()=>changeZoom(2);
$('geo-reset').onclick=()=>{locationView=[0,0,640,320];renderLocation()};
$('geo-close').onclick=()=>{currentLocation=null;$('location-panel').hidden=true};
$('geo-map').onpointerdown=e=>{
 if(e.button!==0)return;
 const pin=e.target.closest('[data-pin]');if(pin)activePin=Number(pin.dataset.pin);
 gesture={id:e.pointerId,x:e.clientX,y:e.clientY,start:svgPoint(e),view:[...locationView],pin:!!pin,region:e.target.closest('[data-region]')?.dataset.region,moved:false};
 e.currentTarget.setPointerCapture(e.pointerId);
};
$('geo-map').onpointermove=e=>{
 if(!gesture||gesture.id!==e.pointerId)return;
 if(Math.hypot(e.clientX-gesture.x,e.clientY-gesture.y)>3)gesture.moved=true;
 if(!gesture.moved)return;
 const point=svgPoint(e);
 if(gesture.pin){placePin(point);return}
 locationView[0]+=gesture.start.x-point.x;locationView[1]+=gesture.start.y-point.y;
 $('geo-map').setAttribute('viewBox',locationView.join(' '));
};
$('geo-map').onpointerup=e=>{
 if(!gesture||gesture.id!==e.pointerId)return;
 const g=gesture;gesture=null;
 if(g.moved&&g.pin)placePin(svgPoint(e));
 if(!g.moved){const state=geoState();if(state.mode==='site'&&!g.pin)placePin(svgPoint(e));else if(state.mode.startsWith('admin'))toggleArea(g.region)}
 renderLocation();
};
$('geo-map').onpointercancel=()=>{gesture=null};
function applyLocation(p,edit){
 if(!edit)return;
 for(const k of ['sites','source_coord','geonames_locality','aliases','kind','place_en','admin1_ids','admin2_ids','admin1_names','admin2_names','admin1_name','admin2_name','scope_label','scope_label_en','_coord_source','_inferred_scope','reviewed_pins','reviewed_unresolved'])delete p[k];
 p.coverage=edit.mode;p._location_basis='manager-reviewed';
 if(edit.evidence?.trim())p._location_evidence=edit.evidence.trim();else delete p._location_evidence;
 if(edit.mode==='site'){
  p.reviewed_pins=edit.pins.filter(hasPin);p.reviewed_unresolved=edit.pins.filter(x=>!hasPin(x)).map(x=>x.name);
  if(!p.reviewed_pins.length){p.coverage='unknown';p.scope_label=p.place||'사업 범위 확인 필요'}
 }else if(edit.mode.startsWith('admin')){
  p[edit.mode+'_ids']=edit.ids;p[edit.mode+'_names']=geo.regions[edit.mode].filter(f=>edit.ids.includes(f.id)).map(f=>f.name);
  if(!edit.ids.length){p.coverage='unknown';p.scope_label=p.place||'사업 범위 확인 필요'}
 }
}
