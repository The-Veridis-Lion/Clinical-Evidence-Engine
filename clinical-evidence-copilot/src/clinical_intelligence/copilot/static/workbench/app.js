import {WorkbenchAPI, rows, capabilitiesList, sourceRefs, sourceSlice, describe, requestId} from './adapter.js';

const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = new WorkbenchAPI();
const state = {patient:null, encounter:null, workspace:null, soap:null, capabilities:[], queued:[], refs:new Map(), refIndex:0, query:null, careflow:null, drawer:null, selected:null, generation:0, evidenceGeneration:0, poll:null, returnFocus:null, uploadBusy:false};
const titles = {S:'Subjective',O:'Objective',A:'Assessment',P:'Plan'};
const queryLabels = {visit_count:'How many registered encounters?',documented_duration_sum:'Total explicitly documented duration',visit_frequency:'Registered encounter frequency',symptom_timeline:'Symptom timeline',observation_history:'Observation history'};
function notify(text, type='') { $('notice').textContent=text; $('notice').className='notice '+type; $('notice').hidden=!text; }
function fail(error) { notify(error.message || String(error),'error'); }
function loading() { return '<div class="loading" role="status" aria-label="Loading saved evidence"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div><p class="hint">Loading saved evidence…</p></div>'; }
function available(name) { const caps=state.workspace?.capabilities || {}; const aliases={careflow:'careflow_shared_evidence',query_interpretation:'natural_language_query',file_upload:'batch_extraction'}; const item=caps[aliases[name] || name]; return item===true || item?.enabled===true || item?.available===true; }
function revision(value){return typeof value==='string' && value.length>18?value.slice(0,10):describe(value);}
function remember(ref) { const key=String(++state.refIndex); state.refs.set(key,ref); return key; }
function refButton(ref, label='View evidence') { return `<button type="button" class="link" data-ref="${remember(ref)}">${esc(label)} ↗</button>`; }
function refsMarkup(refs) {
  const groups=new Map();
  for(const ref of refs){const key=`${ref.case_id || ref.source_id || ref.document_id}:${ref.metadata_only?`metadata:${ref.encounter_id || ''}`:'source'}`;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(ref);}
  return [...groups.values()].map(group=>{const clinical=group.filter(ref=>Number.isInteger(ref.start));const first=clinical[0] || group[0];const label=first.metadata_only?'Encounter association':first.document_id || 'Source';return refButton({...first,all_refs:clinical},`${label}${clinical.length>1?` (${clinical.length} passages)`:''}`);}).join(' · ');
}
function current(generation) { return generation===state.generation; }
function selectedPatient() { if (!state.patient) throw Error('Select or add a patient first.'); return state.patient; }
function setMobile(clinical) { $('workspace-grid').classList.toggle('show-clinical',clinical); $('show-soap').setAttribute('aria-selected',String(!clinical)); $('show-evidence').setAttribute('aria-selected',String(clinical)); }

async function loadPatients(preferred) {
  const response=await api.patients(); const patients=rows(response.patients || response);
  $('patient-select').innerHTML='<option value="">Select patient</option>'+patients.map(p=>`<option value="${esc(p.patient_id)}">${esc(p.display_label || p.patient_id)}</option>`).join('');
  const id=preferred || state.patient || patients[0]?.patient_id;
  if (id && patients.some(p=>p.patient_id===id)) { $('patient-select').value=id; await selectPatient(id); }
}
async function selectPatient(id) {
  if (state.uploadBusy) { $('patient-select').value=state.patient; notify('Wait for the current upload response before changing patients.','warning'); return; }
  clearTimeout(state.poll); state.generation++; state.patient=id || null; state.encounter=null; state.workspace=null; state.soap=null; state.query=null; state.careflow=null; state.refs.clear(); state.queued=[];
  closeEvidence(); renderQueue(); $('query-result').replaceChildren(); $('careflow-detail').hidden=true; $('careflow-requests').replaceChildren(); $('polish-proposal').hidden=true;
  $('patient-id').textContent=id ? `Patient ID: ${id}` : 'Explicit patient identity required'; $('encounter-select').innerHTML='<option value="">Select encounter</option>'; $('encounter-select').disabled=true;
  $('run-query').disabled=true; $('interpret-question').disabled=true; $('create-careflow').disabled=true; $('polish-button').disabled=true;
  if (!id) { $('soap').innerHTML='<div class="empty"><h2>Select a patient</h2><p>Use an explicit patient identity before adding or reading sources.</p></div>'; return; }
  $('soap').innerHTML=loading(); const generation=state.generation;
  try {
    const [workspace,capabilities]=await Promise.all([api.workspace(id),api.capabilities(id)]);
    if (!current(generation)) return;
    state.workspace=workspace; state.capabilities=capabilitiesList(capabilities); renderCapabilities(capabilities); renderWorkspace();
    const encounter=workspace.active_encounter_id || rows(workspace.encounters)[0]?.encounter_id;
    if (encounter) await selectEncounter(encounter); else renderSoap();
    loadCareflow(generation); schedulePoll();
  } catch (error) { if(current(generation)){ $('soap').innerHTML='<div class="empty"><h2>Workspace unavailable</h2><p>Saved sources could not be loaded. Reload the page after the local service is available.</p></div>'; fail(error); } }
}
function renderWorkspace() {
  const w=state.workspace; if (!w) return;
  const encounters=rows(w.encounters);
  $('encounter-select').innerHTML='<option value="">Select encounter</option>'+encounters.map(e=>`<option value="${esc(e.encounter_id)}">${esc(e.encounter_time || e.encounter_date || 'Date unknown')} · ${esc(e.display_label || e.encounter_id)}</option>`).join('');
  $('encounter-select').value=state.encounter || ''; $('encounter-select').disabled=!encounters.length;
  $('evidence-version').textContent=`Evidence revision ${revision(w.evidence_version)} · ${rows(w.documents).length} source document${rows(w.documents).length===1?'':'s'}`;
  $('evidence-version').title=describe(w.evidence_version);
  $('source-list').innerHTML=rows(w.documents).length ? rows(w.documents).map(d=>`<div class="source-row"><strong>${esc(d.filename || d.document_id)}</strong><span class="hint">${esc(d.processing_status || d.status || 'Saved')} · ${esc(d.input_kind || 'Text')}<br>Encounter: ${esc(d.encounter_id || 'Unassigned')} · ${esc(d.encounter_time || 'Date unknown')}</span>${d.packet_version?`<div class="actions">${refButton({case_id:d.case_id,document_id:d.document_id,packet_version:d.packet_version || d.version},'Read original source')}</div>`:''}</div>`).join('') : '<p class="hint">No saved sources yet. Add a note or dialogue to begin.</p>';
  renderJobs();
  $('create-careflow').disabled=!available('careflow') || !rows(w.documents).some(d=>d.packet_version);
  $('careflow-status').textContent=available('careflow') ? 'Shared evidence intake uses saved packets and makes no model calls.' : 'CareFlow sharing is unavailable on this server. The original CareFlow workspace is linked above.';
  renderQueue();
}
async function selectEncounter(id) {
  state.encounter=id || null; state.soap=null; $('encounter-select').value=id || ''; $('polish-proposal').hidden=true; closeEvidence();
  if(!id){renderSoap();return;}
  $('soap').innerHTML=loading(); $('polish-button').disabled=true;
  const generation=state.generation,patient=state.patient;
  try { const soap=await api.soap(patient,id); if (!current(generation) || id!==state.encounter) return; state.soap=soap; renderSoap(); }
  catch(error){if(current(generation)&&id===state.encounter){$('soap').innerHTML='<div class="empty"><h2>Draft unavailable</h2><p>The selected encounter could not be loaded. Its saved sources remain in the Sources tab.</p></div>';fail(error);}}
}
function rowRefs(row) {
  if(rows(row.source_refs).length) return row.source_refs;
  const links=rows(state.soap?.sentence_evidence_links).filter(link=>link.fact_id===row.fact_id || rows(link.fact_ids).includes(row.fact_id));
  const linked=links.flatMap(sourceRefs);
  return linked.length?linked:[{case_id:row.case_id,packet_version:row.packet_version,document_id:row.document_id,fact_id:row.fact_id}];
}
function renderSoap() {
  const soap=state.soap;
  if(!soap){$('soap').innerHTML='<div class="empty"><h2>No encounter selected</h2><p>Add sources with an explicit encounter ID to read a visit-specific SOAP draft. Unassigned files remain available for patient-wide queries.</p><button type="button" data-open-intake class="primary">Add clinical sources</button></div>';$('soap-context').textContent='An encounter is a visit, not a file.';return;}
  const encounter=rows(state.workspace?.encounters).find(e=>e.encounter_id===state.encounter);
  $('soap-context').textContent=`${state.encounter} · ${encounter?.encounter_time || encounter?.encounter_date || 'Date unknown'} · Evidence revision ${revision(soap.evidence_version)}`;
  $('soap').innerHTML=(rows(soap.missing_documents).length?`<p class="warning-text partial-notice">${rows(soap.missing_documents).length} source document(s) for this encounter have incomplete extraction. This draft may be incomplete.</p>`:'')+Object.entries(titles).map(([letter,title])=>`<section class="soap-section"><div class="soap-heading"><span class="soap-letter">${letter}</span><h2>${title}</h2></div><div class="soap-prose">${rows(soap.sections?.[letter]).map((row,index)=>{
    const refs=rowRefs(row); const ref={...refs[0],fact_id:row.fact_id,all_refs:refs};
    const notes=[row.specific_risk?'Specific concern: inspect the source.':null,row.section_note,...rows(row.presentation_notes)].filter(Boolean);
    return `<button type="button" class="soap-claim" aria-pressed="false" data-ref="${remember(ref)}" aria-label="Inspect evidence: ${esc(row.display_text || row.concept)}">${esc(row.display_text || row.concept || 'Source statement')}<sup aria-hidden="true">${index+1}</sup></button>${notes.length?`<span class="claim-caution">${notes.map(esc).join(' ')}</span>`:''}`;
  }).join('') || '<p class="hint">Not documented in the saved extraction.</p>'}</div></section>`).join('');
  const capability=soap.polishing_capability;
  const canPolish=capability===true || capability?.enabled===true || capability?.available===true;
  $('polish-button').disabled=!canPolish;
  $('polish-button').title=canPolish?'Optional extra Luna call. Returns a separate wording proposal.':'Optional wording polish is unavailable on this server.';
}

function addQueued(filename,text,inputKind='note') {
  if (!text.trim()) throw Error(`${filename}: the source is empty.`);
  if (text.includes('\u0000')) throw Error(`${filename}: binary content is not accepted.`);
  const max=state.workspace?.capabilities?.max_source_characters || 80000;
  if(Array.from(text).length>max)throw Error(`${filename}: the server accepts up to ${max.toLocaleString()} characters per original source. This file was not queued.`);
  if(state.queued.filter(f=>!f.sent).length>=(state.workspace?.capabilities?.max_files || 20))throw Error('The upload batch has reached its file limit. Submit or remove queued sources first.');
  state.queued.push({key:requestId(),document_id:`source-${requestId()}`,filename,text,input_kind:inputKind,encounter_id:state.encounter || '',encounter_time:'',status:'Ready to submit'});
}
function renderQueue() {
  $('upload-table').hidden=!state.queued.length;
  $('upload-rows').innerHTML=state.queued.map(file=>`<tr data-queue="${esc(file.key)}"><td><strong>${esc(file.filename)}</strong><small class="hint">${Array.from(file.text).length.toLocaleString()} characters</small></td><td><input aria-label="Encounter ID for ${esc(file.filename)}" data-file-field="encounter_id" value="${esc(file.encounter_id)}" placeholder="Unknown / unassigned" ${file.sent?'disabled':''}></td><td><input type="date" aria-label="Encounter date for ${esc(file.filename)}" data-file-field="encounter_time" value="${esc(file.encounter_time)}" ${file.sent?'disabled':''}></td><td><select aria-label="Input type for ${esc(file.filename)}" data-file-field="input_kind" ${file.sent?'disabled':''}><option value="note" ${file.input_kind==='note'?'selected':''}>Clinical note</option><option value="dialogue" ${file.input_kind==='dialogue'?'selected':''}>Dialogue</option></select></td><td class="${file.error?'error-text':''}">${esc(file.status)}</td><td>${!file.sent?`<button type="button" data-remove-file="${esc(file.key)}" aria-label="Remove ${esc(file.filename)}">Remove</button>`:''}</td></tr>`).join('');
  const live=api.config.live_enabled===true && (!state.workspace || available('file_upload'));
  $('upload-submit').disabled=state.uploadBusy || !state.patient || !state.queued.some(f=>!f.sent) || !live;
  $('upload-help').textContent=!live?'Text extraction is unavailable in this offline server. Existing saved evidence remains readable.':state.uploadBusy?'Saving the batch. Leave this page open. Each file has its own durable job.':'Each new source is extracted once. Duplicate sources reuse saved work; failures are not retried automatically.';
}
function renderJobs() {
  const jobs=rows(state.workspace?.extraction_jobs);
  $('job-list').innerHTML=jobs.length?`<h3 style="margin-top:20px">Source processing</h3>${jobs.map(job=>`<div class="job"><strong>${esc(job.filename || job.document_id)}</strong><span class="${/failed|uncertain|error/.test(job.status)?'error-text':'hint'}">${esc(job.status || job.processing_status || 'Saved')} ${job.error?`· ${esc(describe(job.error))}`:''}</span>${job.case_id?' · Saved extraction available':''}</div>`).join('')}`:'';
}
function schedulePoll() {
  clearTimeout(state.poll);
  const jobs=rows(state.workspace?.extraction_jobs);
  if(!jobs.some(j=>['queued','pending','running','extracting','processing','dispatched'].includes(j.status || j.processing_status)))return;
  const generation=state.generation,patient=state.patient;
  state.poll=setTimeout(async()=>{
    try{const w=await api.workspace(patient);if(!current(generation))return;const changed=w.evidence_version!==state.workspace.evidence_version;state.workspace=w;renderWorkspace();if(changed){invalidateDerived();if(state.encounter)await selectEncounter(state.encounter);else if(w.active_encounter_id)await selectEncounter(w.active_encounter_id);}schedulePoll();}
    catch(error){if(current(generation))fail(error);}
  },3000);
}
async function submitFiles() {
  selectedPatient(); const files=state.queued.filter(f=>!f.sent);if(!files.length)return;
  state.uploadBusy=true;const patient=state.patient;files.forEach(f=>{f.sent=true;f.status='Submitting';});renderQueue();
  try{
    const result=await api.files(patient,files.map(f=>({document_id:f.document_id,filename:f.filename,text:f.text,input_kind:f.input_kind,encounter_id:f.encounter_id.trim() || null,encounter_time:f.encounter_time || null})));
    const jobs=rows(result.jobs || result.extraction_jobs || result.files);
    files.forEach(f=>{const job=jobs.find(j=>j.document_id===f.document_id || j.filename===f.filename);f.status=job?.status || job?.processing_status || 'Accepted; check saved job state';f.error=/error|failed|conflict|rejected/.test(f.status);});
    state.workspace=await api.workspace(patient);renderWorkspace();schedulePoll();
    const encounter=state.encounter || state.workspace.active_encounter_id || rows(state.workspace.encounters)[0]?.encounter_id;
    if(encounter)await selectEncounter(encounter);
    invalidateDerived();notify('Source batch received. Per-file states are listed below; incomplete files are not counted as successful extractions.');
  }catch(error){files.forEach(f=>{f.status='Submission not confirmed. Check saved jobs before trying again.';f.error=true;});fail(error);}
  finally{state.uploadBusy=false;renderQueue();}
}

function renderCapabilities(capabilities) {
  $('query-family').innerHTML='<option value="">Choose a query</option>'+state.capabilities.map(c=>`<option value="${esc(c.family || c.id || c.name)}">${esc(c.label || queryLabels[c.family || c.id || c.name] || describe(c.family || c.id || c.name))}</option>`).join('');
  if(state.capabilities.length)$('query-family').selectedIndex=1;
  $('run-query').disabled=!state.capabilities.length;
  const interpretation=capabilities.natural_language || capabilities.interpretation;
  $('interpret-question').disabled=!(available('query_interpretation') && (interpretation===true || interpretation?.supported===true || interpretation?.enabled===true || interpretation?.available===true));
  $('interpret-question').title=$('interpret-question').disabled?'Natural-language interpretation is unavailable on this server.':'';
  queryFields();
}
function queryFields(){const family=$('query-family').value;const needsConcept=['documented_duration_sum','symptom_timeline','observation_history','visit_frequency'].includes(family);$('query-concept').required=['symptom_timeline','observation_history'].includes(family);$('concept-label').hidden=!needsConcept;}
async function runQuery(natural=false) {
  const patient=selectedPatient(),generation=state.generation; const button=$(natural?'interpret-question':'run-query');
  const filters=Object.fromEntries(Object.entries({start:$('query-start').value,end:$('query-end').value,concept:$('concept-label').hidden?'':$('query-concept').value.trim(),experiencer:$('query-experiencer').value,service_type:$('query-service').value.trim()}).filter(([,v])=>v));
  if(filters.start && filters.end && filters.start>filters.end)throw Error('The end date must be on or after the start date.');
  button.disabled=true;$('query-result').innerHTML=loading();
  try{const result=await api.query(patient,natural?{question:$('question').value.trim(),allow_model:true,request_id:requestId()}:{family:$('query-family').value,filters});if(!current(generation))return;state.query=result;renderQuery(result);}
  catch(error){if(current(generation)){$('query-result').innerHTML='<p class="error-text result-item">The query did not produce a result. No total has been assumed.</p>';fail(error);}}
  finally{if(current(generation))button.disabled=false;}
}
function resultItems(title,items) {
  if(!rows(items).length)return '';
  return `<section class="result-section"><h3>${esc(title)}</h3>${items.map(item=>`<div class="result-item"><p>${esc(resultText(item))}</p>${refsMarkup(sourceRefs(item))}</div>`).join('')}</section>`;
}
function resultText(item){
  if(!item || typeof item!=='object')return describe(item);
  if(item.reason)return `${String(item.reason).replaceAll('_',' ')}${item.document_id?` · ${item.document_id}`:''}${item.record?.concept?` · ${item.record.concept}`:''}`;
  if(item.operation)return `${queryLabels[item.operation] || String(item.operation).replaceAll('_',' ')}: ${item.inputs?.record_count ?? 0} included records. ${Object.entries(item.output || {}).map(([key,value])=>`${key.replaceAll('_',' ')}: ${value}`).join('; ')}`;
  if(item.week_start)return `${item.week_start} to ${item.week_end}: ${item.visit_count} registered encounters${item.observed_start!==item.week_start || item.observed_end!==item.week_end?' (partial week)':''}.`;
  if(item.encounter_id&&!item.concept)return `${item.encounter_date || 'Date unknown'} · ${item.encounter_id}`;
  if(item.concept)return `${item.display_date || item.event_date || item.record_date || 'Date unknown'} · ${item.concept}${item.polarity?` (${item.polarity})`:''}${item.value!=null?`: ${describe(item.value)}`:''}${item.time_basis==='encounter_record'?' · Record date only; event time unknown.':''}`;
  if(item.document_id)return `${item.document_id} · saved version ${item.packet_version ?? 'unknown'}`;
  return describe(item);
}
function renderQuery(result) {
  if(result.status && result.status!=='ready'){$('query-result').innerHTML=`<div class="answer">${esc(result.clarification_question || result.explanation || 'This question needs clarification.')}</div><p class="hint">Luna interpreted the question, but no calculation was run. ${esc(result.explanation || '')}</p>`;return;}
  const answer=result.answer || {},family=result.query_spec?.family;
  let summary=typeof answer==='string'?answer:family==='visit_count'?`${answer.visit_count ?? 'Unknown'} registered encounter${answer.visit_count===1?'':'s'}.`:family==='documented_duration_sum'?answer.documented_minutes==null?'No complete documented duration total is available.':`${answer.documented_minutes} explicitly documented minutes${answer.complete===false?' (incomplete subtotal)':''}.`:family==='visit_frequency'?`${rows(answer.weeks || answer.buckets).length} registered encounter frequency interval${rows(answer.weeks || answer.buckets).length===1?'':'s'}.`: `${rows(answer.events).length} dated record${rows(answer.events).length===1?'':'s'}.`;
  const details=typeof answer==='object'?[...rows(answer.events),...rows(answer.encounters),...rows(answer.weeks || answer.buckets),...rows(answer.recorded_mentions)]:[];
  $('query-result').innerHTML=`<div class="answer">${esc(summary)}</div><p class="hint">${result.model_used_for_interpretation?'Question interpreted with a model; result calculated from saved evidence.':'Calculated from saved evidence. No model call.'} Evidence revision ${esc(revision(result.evidence_version))}.</p>${['visit_count','visit_frequency'].includes(family)?'<p class="hint">Registered encounter IDs do not establish clinical attendance. Prescribed frequency is not counted as attendance.</p>':'<p class="hint">A record date identifies when a statement was documented. Its clinical event time may be unknown; inspect the time basis on each record.</p>'}${resultItems('Documented records',details)}${resultItems('Missing information',result.missing_data)}${resultItems('Calculation',result.calculation_steps)}<details open><summary>Included evidence & exclusions</summary>${resultItems('Included source documents',result.computed_from)}${resultItems('Excluded records',result.excluded_records)}${refsMarkup(rows(result.source_refs))}</details><details><summary>Query audit</summary><pre>${esc(JSON.stringify({query_spec:result.query_spec,answer:result.answer,model_calls:result.model_calls,evidence_version:result.evidence_version},null,2))}</pre></details>`;
}
function invalidateDerived(){if(state.query){$('query-result').insertAdjacentHTML('afterbegin','<p class="warning-text result-item" role="status">Saved evidence changed. Run this query again before using this earlier result.</p>');state.query=null;}if(state.careflow)$('careflow-status').textContent='Evidence changed. Check the request synchronization state and save a new shared revision.';}

async function openEvidence(ref) {
  if(ref.careflow_check){openCareflowEvidence(ref.careflow_check);return;}
  if(!ref.case_id){notify('This result has no saved clinical span. Its encounter association is metadata, not clinical evidence.','warning');return;}
  const patient=selectedPatient(),generation=state.generation,evidenceGeneration=++state.evidenceGeneration;
  state.returnFocus=document.activeElement;$('evidence-drawer').hidden=false;$('evidence-body').innerHTML=loading();$('evidence-title').focus();
  document.querySelectorAll('.soap-claim[aria-pressed=true]').forEach(el=>el.setAttribute('aria-pressed','false'));if(state.returnFocus?.classList.contains('soap-claim'))state.returnFocus.setAttribute('aria-pressed','true');
  try{const result=await api.evidence(patient,ref);if(!current(generation)||evidenceGeneration!==state.evidenceGeneration)return;state.drawer={...result,ref};renderEvidence();}
  catch(error){if(current(generation)&&evidenceGeneration===state.evidenceGeneration){$('evidence-body').innerHTML=`<p class="error-text" style="margin-top:20px">${esc(error.message)}</p>`;}}
}
function closeEvidence(){state.evidenceGeneration++;$('evidence-drawer').hidden=true;state.drawer=null;document.querySelectorAll('.soap-claim[aria-pressed=true]').forEach(el=>el.setAttribute('aria-pressed','false'));if(state.returnFocus?.isConnected)state.returnFocus.focus();}
function marked(text,start,end){return esc(sourceSlice(text,0,start))+'<mark>'+esc(sourceSlice(text,start,end))+'</mark>'+esc(sourceSlice(text,end));}
function evidenceSpans(packet,ref,fact){
  const explicit=rows(ref.all_refs).filter(r=>r.case_id===packet.case_id && Number.isInteger(r.start));
  let spans=explicit.length?explicit:Number.isInteger(ref.start)?[ref]:rows(packet.evidence).filter(e=>rows(fact?.evidence_ids).includes(e.evidence_id));
  if(!spans.length && fact?.assertion?.evidence)spans=[fact.assertion.evidence,...rows(fact.assertion.supporting_evidence)];
  const unique=new Map();for(const span of spans)unique.set(`${span.start}:${span.end}`,span);
  return [...unique.values()].sort((a,b)=>a.start-b.start);
}
function renderEvidence() {
  const {packet,presentation,history,ref}=state.drawer; if(!packet?.source){$('evidence-body').innerHTML='<p class="error-text">The saved packet does not contain its original source.</p>';return;}
  const fact=rows(packet.facts).find(f=>f.fact_id===ref.fact_id),assertion=fact?.assertion;
  const spans=evidenceSpans(packet,ref,fact); const source=packet.source.text || '';const points=Array.from(source);
  const navigation=presentation?.source_navigation;const segments=rows(navigation?.segments);
  $('evidence-title').textContent=assertion?.concept || 'Source passage';
  const temporal=semanticsProposal(packet,ref.fact_id);
  const event=temporal?.event_time || assertion?.attributes?.event_time;
  const spanHtml=spans.map((span,index)=>{
    const exact=Number.isInteger(span.start)&&Number.isInteger(span.end)&&span.start>=0&&span.end>span.start&&span.end<=points.length&&sourceSlice(source,span.start,span.end)===span.quote;
    let start=Math.max(0,span.start-300),end=Math.min(points.length,span.end+400);
    const intersect=segments.map((seg,i)=>({seg,i})).filter(({seg})=>seg.start<span.end&&seg.end>span.start);
    if(intersect.length){let first=Math.max(0,intersect[0].i-1),last=Math.min(segments.length-1,intersect.at(-1).i+1);if(first>0&&/patient/i.test(segments[first].raw_speaker_label || ''))first--;if(last<segments.length-1&&/[?？]\s*$/.test(sourceSlice(source,segments[last].start,segments[last].end).trim()))last++;start=segments[first].start;end=segments[last].end;}
    return `<section class="citation"><h3>Passage ${index+1}</h3><p class="hint">Characters ${esc(span.start)}–${esc(span.end)} · ${exact?'Exact saved source span':'Source span could not be verified'}</p>${exact?`<div class="quoted-source">${start?'…\n':''}${marked(sourceSlice(source,start,end),span.start-start,span.end-start)}${end<points.length?'\n…':''}</div>`:`<blockquote>${esc(span.quote || 'No quoted text provided')}</blockquote>`}</section>`;
  }).join('');
  $('evidence-body').innerHTML=`<div class="drawer-meta"><div>Document<strong>${esc(packet.source.document_id)}</strong></div><div>Saved packet<strong>Version ${esc(packet.version)}</strong></div><div>Encounter date<strong>${esc(packet.source.encounter_time || 'Not documented')}</strong></div><div>Assertion event time<strong>${esc(describe(event || 'Not asserted'))}</strong></div></div>${ref.metadata_only?`<p class="warning-text">Explicit encounter association: ${esc(ref.encounter_id || 'Unknown')} · ${esc(ref.encounter_time || 'Date unknown')}. This registration metadata does not establish clinical attendance or a clinical event.</p>`:''}<p class="hint">Passages follow the original source order. Questions and answers are shown together with surrounding context. Event time and encounter date can differ.</p>${spanHtml || '<p class="hint">No individual citation was selected. Read the complete original source below.</p>'}<details ${!spans.length?'open':''}><summary>Full original source</summary><div class="quoted-source source-full">${esc(source)}</div></details>${fact?`<div class="actions"><button type="button" id="open-correction">Edit this fact</button><span class="hint">A correction saves a new version.</span></div><div id="correction-container"></div>`:''}<details><summary>Saved revision history</summary>${rows(history?.versions || history).map(h=>`<div class="history-item">${refButton({case_id:packet.case_id,packet_version:h.version,fact_id:ref.fact_id},`View version ${h.version}`)} · ${esc(h.created_at || '')}</div>`).join('') || '<p class="hint">No revision list was returned.</p>'}<a href="/?case=${encodeURIComponent(packet.case_id)}" target="_blank" rel="noopener">Open original Copilot workspace ↗</a></details><details><summary>Source audit</summary><pre>${esc(JSON.stringify({case_id:packet.case_id,version:packet.version,document_id:packet.source.document_id,fact_id:ref.fact_id,source_hash:packet.source.source_hash,offset_unit:packet.source.offset_unit},null,2))}</pre></details>`;
  if($('open-correction')){
    const latest=Math.max(packet.version,...rows(history?.versions || history).map(h=>h.version));
    if(packet.version<latest){$('open-correction').disabled=true;$('open-correction').insertAdjacentHTML('afterend',`<p class="hint">Historical version. ${refButton({case_id:packet.case_id,packet_version:latest,fact_id:ref.fact_id},'View latest to edit')}</p>`);}
    $('open-correction').onclick=()=>renderCorrection(false);
    if(packet.extraction_metadata?.soap_projection_version==='soap/v6'&&packet.version===latest){
      $('open-correction').insertAdjacentHTML('afterend','<button type="button" id="open-semantics">Edit timing & actions</button>');
      $('open-semantics').onclick=()=>renderCorrection(true);
    }
  }
}
const factFields=[['concept','Clinical concept'],['original_term','Original term'],['polarity','Polarity',['present','absent','uncertain']],['temporality','Time scope',['current','historical','planned','unknown']],['experiencer','Subject',['patient','family','other','unknown']],['clinical_status','Documented status'],['attributes.severity','Severity'],['attributes.duration','Duration'],['attributes.value','Value'],['attributes.unit','Unit']];
const timingFields=[['frequency','Documented frequency'],['event_time','Clinical event time'],['duration','Documented duration'],['action_state','Action state',['planned','completed','not_completed','ongoing','discussed','unknown']],['completion_scope','Completion scope',['','single_event','course','full_course','unknown']],['assertion_basis','Reporting basis',['patient_report','patient_reported','clinician_assessment','clinician_observation','documented_history','discussion','unknown']],['action_type','Action type']];
const getField=(obj,key)=>key.split('.').reduce((v,k)=>v?.[k],obj);
function semanticsProposal(packet,factId){
  const claim=rows(packet.extraction_metadata?.evidence_verification?.assertions).find(r=>r.fact_id===factId)?.proposed_claim;
  const old=rows(packet.extraction_metadata?.clinical_semantics_v2).find(r=>r.fact_id===factId)?.semantics;
  return claim?{version:'clinical-fact-semantics/2',frequency:claim.attributes?.frequency??null,event_time:claim.event_time??null,duration:claim.attributes?.duration??null,action_state:claim.action_state??'unknown',completion_scope:claim.completion_scope??null,assertion_basis:claim.reporting_basis??'unknown',action_type:claim.action_type??null}:old || {version:'clinical-fact-semantics/2',frequency:null,event_time:null,duration:null,action_state:'unknown',completion_scope:null,assertion_basis:'unknown',action_type:null};
}
function renderCorrection(semantics=false) {
  const {packet,ref}=state.drawer,fact=rows(packet.facts).find(f=>f.fact_id===ref.fact_id);
  if(!fact)return;
  state.drawer.editingSemantics=semantics;
  $('correction-container').innerHTML=`<form id="correction-form" class="review-form"><h3>${semantics?'Correct timing and action attributes':'Save a fact correction'}</h3><p class="hint">Change the incorrect fields. Original text, citations and earlier revisions are retained. Review the cited passage after editing.</p><div class="fields">${(semantics?timingFields:factFields).map(([key,label,choices])=>{const value=getField(semantics?semanticsProposal(packet,fact.fact_id):fact.assertion,key)??'';return `<label>${label}${choices?`<select data-correction-field="${key}">${[...new Set([...choices,value])].map(c=>`<option value="${esc(c)}" ${c===value?'selected':''}>${esc(c || 'Not asserted')}</option>`).join('')}</select>`:`<input data-correction-field="${key}" value="${esc(value)}" ${key==='original_term'?'required':''}>`}</label>`;}).join('')}</div><label>Reviewer identity<input id="correction-reviewer" required maxlength="160" autocomplete="name"></label><label>Reason and source interpretation<textarea id="correction-reason" rows="3" required maxlength="4000"></textarea></label><div class="actions"><button type="button" id="cancel-correction">Cancel</button><button type="submit" class="primary">Save new version</button></div><p id="correction-status" class="hint" role="status"></p></form>`;
  $('cancel-correction').onclick=()=>{$('correction-container').replaceChildren();};$('correction-form').onsubmit=saveCorrection;$('correction-form').querySelector('input').focus();
}
function openCareflowEvidence(check) {
  const packet=state.careflow;if(!packet)return;
  state.returnFocus=document.activeElement;state.evidenceGeneration++;state.drawer=null;
  $('evidence-drawer').hidden=false;$('evidence-title').textContent=check.description || check.requirement || 'Material evidence';$('evidence-title').focus();
  const facts=[...rows(packet.facts).filter(f=>rows(check.fact_ids).includes(f.fact_id)),...rows(packet.excluded_facts).filter(f=>f.requirement===check.requirement)];
  const mappedIds=new Set(rows(packet.clinical_mapping?.decisions).filter(d=>rows(d.derived_fact_ids).some(id=>rows(check.fact_ids).includes(id))).flatMap(d=>rows(d.binding?.clinical_fact_ids)));
  const clinical=rows(packet.clinical_context).flatMap(context=>rows(context.facts).filter(f=>mappedIds.has(f.context_fact_id)).flatMap(f=>[f.evidence,...rows(f.supporting_evidence)].filter(Boolean).map(ref=>({...ref,source_id:context.source_id}))));
  const materialRefs=[...clinical,...facts.flatMap(f=>[...rows(f.citations),...rows(f.requirement_support?.source_refs),...rows(f.requirement_support?.semantic_evidence_bundle?.context_spans)])];
  const sourceIds=new Set([...materialRefs.map(r=>r.source_id),...facts.flatMap(f=>rows(f.evidence).map(r=>r.source_id))]);
  for(const source of rows(packet.sources).filter(s=>sourceIds.has(s.source_id))){const original=source.content?.original_document?.source_id;if(original){sourceIds.add(original);for(const field of Object.values(source.content.original_field_evidence || {})){for(const span of Array.isArray(field)?field:[field])if(span&&typeof span==='object')materialRefs.push({...span,source_id:original});}}}
  const sources=rows(packet.sources).filter(source=>sourceIds.has(source.source_id));
  $('evidence-body').innerHTML=`<div class="drawer-meta"><div>Request<strong>${esc(packet.request?.request_id)}</strong></div><div>Saved revision<strong>${esc(packet.revision)}</strong></div></div><p>${esc(check.reason || '')}</p>${[...rows(check.gaps),...rows(check.review_questions)].map(g=>`<p class="warning-text">${esc(describe(g))}</p>`).join('')}${facts.map(f=>`<div class="citation"><h3>${esc(careflowFactLabel(f,packet))}</h3><p class="hint">${esc(f.requirement_support?.status || f.reconciliation_status || 'Saved assertion')} · ${esc(rows(f.citations).find(r=>r.quote)?.source_id || rows(f.evidence)[0]?.source_id || '')}</p>${rows(f.requirement_support?.issues).map(i=>`<p>${esc(describe(i).replaceAll('_',' '))}</p>`).join('')}<details><summary>Assertion audit</summary><p class="hint">${esc(f.statement)}</p></details></div>`).join('')}${sources.map(source=>{const locator=source.original_locator,spans=materialRefs.filter(r=>r.source_id===source.source_id);return `<section class="citation"><h3>${esc(locator?.document_id || source.source_id)}</h3>${locator?.case_id?refsMarkup(spans.length?spans.map(span=>({case_id:locator.case_id,packet_version:locator.version,document_id:locator.document_id,...span})):[{case_id:locator.case_id,packet_version:locator.version,document_id:locator.document_id}]):''}${materialSpans(spans,source)}<details><summary>Complete received source</summary><div class="quoted-source source-full">${esc(typeof source.content==='string'?source.content:JSON.stringify(source.content,null,2))}</div></details></section>`;}).join('') || '<p class="hint">No received source was linked to this check. The gap remains explicit.</p>'}`;
}
function materialSpan(span,source){
  if(!span.quote)return span.raw_value!=null?`<p class="result-item">${esc(describe(span.raw_value))}</p>`:'';
  const text=typeof source.content==='string'?source.content:null;
  const exact=text!=null&&Number.isInteger(span.start)&&Number.isInteger(span.end)&&span.start>=0&&span.end>span.start&&sourceSlice(text,span.start,span.end)===span.quote;
  if(!exact)return `<blockquote>${esc(span.quote)}</blockquote><p class="hint">${esc(span.field || span.locator || 'Saved source quotation')}</p>`;
  const start=Math.max(0,span.start-180),end=Math.min(Array.from(text).length,span.end+240);
  return `<p class="hint">Characters ${span.start}–${span.end} · Exact original source span</p><div class="quoted-source">${start?'…':''}${marked(sourceSlice(text,start,end),span.start-start,span.end-start)}${end<Array.from(text).length?'…':''}</div>`;
}
function careflowFactLabel(fact,packet){
  const source=rows(packet.sources).find(s=>s.source_id===rows(fact.evidence)[0]?.source_id);
  const type=source?.content?.material?.document_type;
  if(type)return `Received ${type.replaceAll('_',' ')}`;
  const ids=new Set(rows(packet.clinical_mapping?.decisions).filter(d=>rows(d.derived_fact_ids).includes(fact.fact_id)).flatMap(d=>rows(d.binding?.clinical_fact_ids)));
  const clinical=rows(packet.clinical_context).flatMap(c=>rows(c.facts).filter(f=>ids.has(f.context_fact_id)));
  if(clinical.length)return clinical.map(f=>`${f.concept}: ${f.clinical_status || f.polarity || 'Saved clinical assertion'}`).join('; ');
  return `${String(fact.requirement || 'Clinical evidence').replaceAll('_',' ')}: saved assertion`;
}
function materialSpans(spans,source){
  const unique=[...new Map(spans.map(span=>[`${span.start}:${span.end}:${span.quote || span.locator || span.field}`,span])).values()];
  if(typeof source.content!=='string')return '<p class="hint">Stored structured fields are available in the source audit below.</p>';
  const text=source.content,length=Array.from(text).length;
  const exact=unique.filter(span=>Number.isInteger(span.start)&&Number.isInteger(span.end)&&span.start>=0&&span.end>span.start&&span.end<=length&&sourceSlice(text,span.start,span.end)===span.quote).sort((a,b)=>a.start-b.start||a.end-b.end);
  if(!exact.length)return unique.map(span=>materialSpan(span,source)).join('');
  const groups=[];
  for(const span of exact){const start=Math.max(0,span.start-180),end=Math.min(length,span.end+240),last=groups.at(-1);if(last&&start<=last.end){last.end=Math.max(last.end,end);last.spans.push(span);}else groups.push({start,end,spans:[span]});}
  return groups.map(group=>{
    let cursor=group.start,html='';
    for(const span of group.spans){if(span.end<=cursor)continue;html+=esc(sourceSlice(text,cursor,Math.max(cursor,span.start)));html+='<mark>'+esc(sourceSlice(text,Math.max(cursor,span.start),span.end))+'</mark>';cursor=span.end;}
    html+=esc(sourceSlice(text,cursor,group.end));
    return `<p class="hint">${group.spans.length} exact original source span${group.spans.length===1?'':'s'} · Characters ${group.spans[0].start}–${group.spans.at(-1).end}</p><div class="quoted-source">${group.start?'…':''}${html}${group.end<length?'…':''}</div><details><summary>Exact field coordinates</summary>${group.spans.map(span=>`<p class="result-item">[${span.start}:${span.end}] ${esc(span.quote)}</p>`).join('')}</details>`;
  }).join('');
}
async function saveCorrection(event) {
  event.preventDefault();const drawer=state.drawer;if(!drawer)return;const {packet,ref}=drawer,fact=rows(packet.facts).find(f=>f.fact_id===ref.fact_id);const replacement=structuredClone(drawer.editingSemantics?semanticsProposal(packet,fact.fact_id):fact.assertion);
  for(const input of $('correction-form').querySelectorAll('[data-correction-field]')){const keys=input.dataset.correctionField.split('.');const value=input.value===''?null:input.value;if((getField(replacement,input.dataset.correctionField)??null)===value)continue;if(keys.length===2){replacement[keys[0]]={...(replacement[keys[0]]||{}),[keys[1]]:value};}else replacement[keys[0]]=value;}
  const button=event.submitter;button.disabled=true;const patient=state.patient,generation=state.generation;
  try{const result=await api.correction(patient,packet.case_id,fact.fact_id,{base_version:packet.version,fact_id:fact.fact_id,...(drawer.editingSemantics?{kind:'semantics'}:{action:'correct'}),reason:$('correction-reason').value,evidence_ids:fact.evidence_ids,reviewer:{reviewer_id:$('correction-reviewer').value,reviewer_type:'human',version:'workbench/1'},...(drawer.editingSemantics?{semantics:replacement}:{replacement})});if(!current(generation))return;invalidateDerived();state.workspace=await api.workspace(patient);renderWorkspace();const encounter=state.encounter;if(encounter){const soap=await api.soap(patient,encounter);if(current(generation)&&encounter===state.encounter){state.soap=soap;renderSoap();}}await openEvidence({...ref,packet_version:result.version || result.packet?.version,all_refs:undefined});notify(`Correction saved as version ${result.version || result.packet?.version || 'returned by the server'}. Earlier versions are retained.${rows(result.careflow_sync).some(r=>r.status==='stale')?' CareFlow synchronization is stale; inspect the request before using its prior result.':''}`);loadCareflow(generation);}
  catch(error){if($('correction-status')){$('correction-status').textContent=error.status===409?'A newer version exists. Close this panel and reopen the statement before saving again.':error.message;$('correction-status').className='error-text';}else fail(error);}
  finally{if(button.isConnected)button.disabled=false;}
}

async function loadCareflow(generation=state.generation) {
  if(!state.patient || !available('careflow'))return;
  try{const response=await api.careflow(state.patient);if(!current(generation))return;const requests=rows(response.requests || response.cases || response);$('careflow-requests').innerHTML=requests.length?requests.map(c=>`<div class="request-row"><strong>${esc(c.request_id || c.case_id)}</strong><span class="hint">${esc(c.request_type || '')} · ${esc(c.readiness || c.status || 'Saved')} · Revision ${esc(c.revision || '?')}</span>${c.stale?'<p class="warning-text">Shared evidence changed. Sync a new revision.</p>':''}<div>${`<button type="button" class="link" data-careflow="${esc(c.case_id)}">Open material check ↗</button>`}</div></div>`).join(''):'<p class="hint">No saved requests for this patient.</p>';}
  catch(error){if(current(generation))$('careflow-status').textContent=`CareFlow unavailable: ${error.message}`;}
}
async function showCareflow(id) {
  const generation=state.generation,selection=(state.careflowGeneration || 0)+1;state.careflowGeneration=selection;
  state.careflow=null;$('careflow-detail').hidden=false;$('careflow-detail').innerHTML=loading();
  const response=await api.careflow(selectedPatient(),`/${encodeURIComponent(id)}`);if(!current(generation)||selection!==state.careflowGeneration)return;
  const packet=response.packet || response;state.careflow=packet;
  $('careflow-detail').hidden=false;
  const checks=rows(packet.checks || packet.checklist?.checks || packet.checklist || packet.requirement_results);
  $('careflow-detail').innerHTML=`<p class="readiness">${esc(packet.readiness || 'Material check')}</p><p class="hint">${esc(packet.request?.request_id || packet.case_id)} · Revision ${esc(packet.revision)}. Readiness reflects the declared project checklist, not insurer approval.</p>${response.shared_binding?.stale || response.shared_binding?.status==='stale' || packet.shared_evidence_stale?'<p class="warning-text">Saved clinical evidence has changed. This request needs a new shared revision.</p>':''}<div class="actions"><button type="button" id="sync-careflow">Sync saved evidence</button><button type="button" id="recalculate-careflow">Recalculate</button></div>${checks.map(check=>`<div class="check-row"><h3>${esc(check.description || check.label || check.requirement || check.name)}</h3><span class="badge">${esc(check.status || check.result || 'Unknown')}</span><p>${esc(check.explanation || check.reason || check.next_action || '')}</p>${refButton({careflow_check:check},'View evidence & gaps')}${[...rows(check.gaps),...rows(check.review_questions),...rows(check.missing || check.missing_fields)].map(m=>`<p class="warning-text">${esc(describe(m))}</p>`).join('')}</div>`).join('') || '<p class="hint">The server returned no checklist entries. Inspect the original workspace for full details.</p>'}<details><summary>Add a formal received document</summary><p class="hint">Paste original labelled fields, one label: value per line. Preserve the patient, request, service and code system on the actual document. These values are not filled from the clinical evidence.</p><form id="material-form"><label>Document ID<input name="document_id" required maxlength="160"></label><div class="fields"><label>Document type<select name="document_type"><option value="provider_order">Provider order</option><option value="referral_request">Referral request</option><option value="prior_authorization_request">PA request</option><option value="prior_authorization_form">PA form</option><option value="payer_request">Payer request</option><option value="request_requirements">Request requirements</option><option value="therapy_record">Therapy record</option><option value="investigation_report">Investigation report</option></select></label><label>Received date<input name="received_at" type="date" required></label></div><label>Original labelled document<textarea name="text" rows="6" required placeholder="Patient ID: …&#10;Request ID: …&#10;Service code: …&#10;Code system: …"></textarea></label><label>Receipt reason<input name="reason" required maxlength="2000"></label><button class="primary">Receive document & recalculate</button></form></details><details><summary>Request audit</summary><pre>${esc(JSON.stringify({case_id:packet.case_id,revision:packet.revision,shared_evidence:packet.shared_evidence || packet.shared_evidence_refs,audit:packet.audit},null,2))}</pre></details>`;
  $('sync-careflow').onclick=()=>mutateCareflow('sync-shared');$('recalculate-careflow').onclick=()=>mutateCareflow('recalculate');$('material-form').onsubmit=saveMaterial;
}
async function mutateCareflow(operation) {
  const packet=state.careflow;if(!packet)return;const button=$(operation==='sync-shared'?'sync-careflow':'recalculate-careflow');button.disabled=true;
  try{await api.careflow(selectedPatient(),`/${encodeURIComponent(packet.case_id)}/${operation}`,{expected_revision:packet.revision,basis_packet_sha256:packet.packet_sha256,actor_id:'local-workbench',reason:'Explicit workbench recalculation from saved evidence'});await showCareflow(packet.case_id);await loadCareflow();notify('Saved a new request revision from the current shared evidence.');}catch(error){fail(error);}finally{if(button.isConnected)button.disabled=false;}
}
async function saveMaterial(event) {
  event.preventDefault();const packet=state.careflow;if(!packet)return;const data=Object.fromEntries(new FormData(event.target));const button=event.submitter;button.disabled=true;
  try{await api.careflow(selectedPatient(),`/${encodeURIComponent(packet.case_id)}/documents`,{expected_revision:packet.revision,document:{document_id:data.document_id,document_type:data.document_type,received_at:data.received_at,text:data.text},intake:{actor_id:'local-workbench',actor_type:'intake_service',basis_revision:packet.revision,basis_packet_sha256:packet.packet_sha256,reason:data.reason}});await showCareflow(packet.case_id);await loadCareflow();notify('Received document saved. The material checklist was recalculated.');}catch(error){fail(error);}finally{if(button.isConnected)button.disabled=false;}
}

$('add-patient').onclick=()=>{$('patient-form').hidden=false;$('patient-form').querySelector('input').focus();};
$('patient-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{const values=Object.fromEntries(new FormData(event.target));values.patient_id=values.patient_id.trim();values.display_label=values.display_label.trim();await api.createPatient(values);await loadPatients(values.patient_id);$('patient-form').hidden=true;event.target.reset();notify('Patient saved. Add the original source records to begin.');}catch(error){fail(error);}finally{button.disabled=false;}};
$('patient-select').onchange=()=>selectPatient($('patient-select').value);
$('encounter-select').onchange=()=>selectEncounter($('encounter-select').value);
function openIntake(){$('intake').hidden=false;if(!state.patient)notify('Add or select a patient before submitting source files.','warning');$('intake').scrollIntoView({block:'start'});}
$('open-intake').onclick=openIntake;$('start-intake').onclick=openIntake;
document.addEventListener('click',event=>{const close=event.target.closest('[data-close]');if(close)$(close.dataset.close).hidden=true;const intake=event.target.closest('[data-open-intake]');if(intake)openIntake();const ref=event.target.closest('[data-ref]');if(ref){const value=state.refs.get(ref.dataset.ref);if(value)openEvidence(value);}const remove=event.target.closest('[data-remove-file]');if(remove){state.queued=state.queued.filter(f=>f.key!==remove.dataset.removeFile);renderQueue();}const careflow=event.target.closest('[data-careflow]');if(careflow)showCareflow(careflow.dataset.careflow).catch(fail);});
$('paste-form').onsubmit=event=>{event.preventDefault();try{const data=Object.fromEntries(new FormData(event.target));addQueued(data.filename,data.text,data.input_kind);event.target.elements.text.value='';renderQueue();notify('Source added to the list. Review its encounter association before extracting.');}catch(error){fail(error);}};
$('file-input').onchange=async event=>{const input=event.target;for(const file of input.files){try{if(!/\.(txt|md|text)$/i.test(file.name))throw Error(`${file.name}: choose a UTF-8 text or Markdown file.`);if(file.size>4*1024*1024)throw Error(`${file.name}: split oversized inputs only according to the server's source policy; this upload supports files up to 4 MiB.`);const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());addQueued(file.name,text);}catch(error){fail(error);}}input.value='';renderQueue();};
$('upload-rows').addEventListener('input',event=>{const input=event.target.closest('[data-file-field]'),row=event.target.closest('[data-queue]');if(!input||!row)return;const file=state.queued.find(f=>f.key===row.dataset.queue);if(file&&!file.sent)file[input.dataset.fileField]=input.value;});
$('upload-submit').onclick=()=>submitFiles().catch(fail);
$('cf-target').onchange=()=>{$('cf-concept').required=Boolean($('cf-target').value);};
$('query-family').onchange=queryFields;$('query-form').onsubmit=event=>{event.preventDefault();runQuery().catch(fail);};$('question-form').onsubmit=event=>{event.preventDefault();runQuery(true).catch(fail);};
for(const name of ['query','careflow','sources'])$('tab-'+name).onclick=()=>{for(const tab of ['query','careflow','sources']){$('tab-'+tab).setAttribute('aria-selected',String(tab===name));$('pane-'+tab).hidden=tab!==name;}};
for(const name of ['query','careflow','sources'])$('tab-'+name).onkeydown=event=>{if(!['ArrowRight','ArrowLeft','Home','End'].includes(event.key))return;event.preventDefault();const tabs=['query','careflow','sources'];let index=tabs.indexOf(name);index=event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3;$('tab-'+tabs[index]).click();$('tab-'+tabs[index]).focus();};
$('show-soap').onclick=()=>setMobile(false);$('show-evidence').onclick=()=>setMobile(true);
$('close-evidence').onclick=closeEvidence;document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('evidence-drawer').hidden)closeEvidence();});
$('polish-button').onclick=async()=>{const button=$('polish-button'),patient=state.patient,encounter=state.encounter,generation=state.generation;button.disabled=true;notify('Organizing saved statements into paragraphs with an extra Luna call. Clinical wording is retained.');try{const result=await api.polish(patient,encounter,state.soap.evidence_version);if(!current(generation)||encounter!==state.encounter)return;$('polish-proposal').hidden=false;$('polish-proposal').innerHTML=`<h3>Separate paragraph proposal</h3><p class="hint">Conservative polish: clinical wording is retained; paragraph grouping only. This proposal has not replaced the saved SOAP.</p>${result.stale?'<p class="warning-text">Evidence changed while this proposal was prepared. Reload the encounter.</p>':''}${Object.entries(result.proposal?.sections || {}).map(([section,paragraphs])=>`<h3>${esc(titles[section] || section)}</h3>${rows(paragraphs).map(p=>`<p>${esc(p.text)}</p>${refsMarkup(rows(p.source_refs))}`).join('')}`).join('')}<details><summary>Call receipt</summary><pre>${esc(JSON.stringify(result.receipt || result.call_receipt || {},null,2))}</pre></details>`;notify('Wording proposal returned separately. Inspect its linked sources before use.');}catch(error){fail(error);}finally{if(current(generation))button.disabled=false;}};
$('careflow-form').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{const patient=selectedPatient(),data=Object.fromEntries(new FormData(event.target));const request={request_id:data.request_id,patient_id:patient,encounter_id:state.encounter,request_type:data.request_type,service_code:data.service_code,code_system:data.code_system,requested_service_date:data.requested_service_date || null,ruleset_id:data.request_type==='referral'?'careflow-referral':'careflow-pa',ruleset_version:'1.0.0'};const result=await api.careflow(patient,'',{case_id:`request-${requestId()}`,request,review_as_of:new Date().toISOString().slice(0,10),received_at:new Date().toISOString().slice(0,10),clinical_reason:data.clinical_reason || null,clinical_associations:data.target_requirement?[{requirement:data.target_requirement,concept:data.target_concept,category:data.target_category,clinical_purpose:data.target_purpose}]:[],summary_case_ids:data.attach_summary?rows(state.workspace.documents).filter(d=>d.packet_version).map(d=>d.case_id):[],materials:[]});await loadCareflow();const id=result.packet?.case_id || result.case_id;if(id)await showCareflow(id);notify('Request created from saved clinical evidence. Add formal received documents to fill material gaps.');}catch(error){fail(error);}finally{button.disabled=!available('careflow');}};

async function initialize(){try{const config=await api.initialize();$('connection').textContent=config.live_enabled?'Luna extraction available':'Offline · saved evidence';if(config.careflow_url)$('careflow-link').href=config.careflow_url;await loadPatients();renderQueue();}catch(error){$('connection').textContent='Connection unavailable';fail(error);$('query-family').innerHTML='<option value="">Queries unavailable</option>';}}
initialize();
