'use strict';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let config, cases = [], packet, presentation, selected, history = [], activeTab = 'source';
let toastTimer;
let omissionTarget = null;
let semanticTarget = false;
let correctionProposal;
let focusedEvidence = null;
let focusedRelationshipSpan = null;
let caseLoadSequence = 0, caseLoading = false, caseReady = false, requestedCaseId;
function canEditCurrent() { return caseReady && !caseLoading && packet && presentation?.packet_hash===packet.content_hash && packet.version===history.at(-1)?.version; }
function requireCurrentVersion() { if(canEditCurrent())return true;toast('Wait for the latest saved version to finish loading before editing.',true);return false; }
function setCaseLoading(loading,ready=caseReady) {
  caseLoading=loading;caseReady=ready;
  $('workspace').setAttribute('aria-busy',String(loading));
  for(const id of ['soap','inspector','detail-panel'])$(id).hidden=loading||!ready;
  for(const id of ['open-review','edit-semantics','reprocess']){const button=$(id);if(button)button.disabled=!canEditCurrent();}
  for(const button of document.querySelectorAll('#review-form button[type="submit"], #reprocess-form button[type="submit"]'))button.disabled=!canEditCurrent();
  if(!canEditCurrent())for(const button of document.querySelectorAll('[data-omission], [data-complete-eligible]'))button.disabled=true;
  for(const id of ['export-json','export-md','export-audit-md','compare'])$(id).disabled=loading||!ready;
  if(loading){
    $('review-dialog').close();$('reprocess-dialog').close();omissionTarget=null;semanticTarget=false;
    $('review-count').textContent='Loading saved version…';$('check-count').textContent='';
    $('note-notice').textContent='Loading the selected encounter and its evidence. Editing is disabled until the saved version is ready.';
  }else if(!ready)$('note-notice').textContent='The selected version could not be loaded. Select an encounter or saved version to retry.';
}
function setCorrectionProposal(value, semantics=false) { correctionProposal=structuredClone(value); $('replacement').value=JSON.stringify(value,null,2); $('use-json').checked=false; $('advanced-correction').open=false; CopilotEditor.render($('field-editor'),value,semantics,presentation?.source_navigation?.available_passages||[]); }
function correctionValue() { return $('use-json').checked?JSON.parse($('replacement').value):CopilotEditor.collect($('field-editor'),correctionProposal,semanticTarget); }
function verificationPanel(f) {
  const record = packet.extraction_metadata.evidence_verification?.assertions.find(r=>r.fact_id===f.fact_id);
  if (!record) return '<p class="field-help">Source semantics UNVERIFIED in this historical projection.</p>';
  const result=record.result;
  const shown=presentedFact(f.fact_id);
  const human=shown?.human_review;
  const humanNote=human?`<p class="human-review-note">Human ${esc(human.action)} by ${esc(human.reviewer_id)} · v${human.version}. ${esc(human.reason)} ${shown.human_review_complete?'Review task completed.':'Decision saved; outstanding questions remain.'} Automatic source checks retain their own result.</p>`:'<p class="field-help">Human review is optional. Record a decision or edit a specific field below.</p>';
  const checkLabel=result.status==='INSUFFICIENT_EVIDENCE'?'Automatic semantic check incomplete':result.status==='SUPPORTED_BY_SOURCE'?'Automatically source-supported':'Automatic source check: '+result.status;
  const typed=packet.extraction_metadata.clinical_semantics_v2?.find(row=>row.fact_id===f.fact_id);
  const support=record.semantic_support_refs?.map(s=>`<p class="field-help">${esc(s.support_scope)} · characters ${s.start}–${s.end}</p><blockquote class="quote">${esc(s.quote)}</blockquote>`).join('') || '';
  const anchor=record.primary_reference_proposal;
  const notAdopted=record.adoption?.not_adopted_dimensions||[];
  const adoptionNote=notAdopted.length?`<p class="field-help">Not adopted into the draft: ${notAdopted.map(d=>esc(d.dimension)).join(', ')}. Original values remain in the proposal audit; the source check has not established these dimensions.</p>`:'';
  return `<div class="verification-check ${shown?.specific_risk?'specific-risk':''}"><b>${esc(checkLabel)}</b>${humanNote}<p class="field-help">Recorded route: ${esc(result.risk_route)}</p><p>Retained check history: ${esc(result.reasons.join(' '))}</p>${support?`<details open><summary>Source-verified supporting passages</summary>${support}</details>`:''}${anchor?`<details><summary>Extraction anchor proposal</summary><p class="field-help">${esc(anchor.status)}. ${packet.extraction_metadata.structured_extraction_contract?.primary_reference_application==='model-selected-primary/1'?'The selected primary passage appears first. Original citation order is retained in the raw response and audit metadata.':'Original citation order retained.'}</p>${anchor.span?`<blockquote class="quote">${esc(anchor.span.quote)}</blockquote>`:'No primary passage proposed.'}</details>`:''}${adoptionNote}<details><summary>Dimension evidence</summary><pre class="code-input">${esc(JSON.stringify(result.dimension_checks,null,2))}</pre></details>${typed?`<details><summary>Typed attribute & event proposals</summary><p class="field-help">Unverified dimensions require targeted review.</p><pre class="code-input">${esc(JSON.stringify(typed.semantics,null,2))}</pre></details>`:''}<p class="field-help">Independent clinical validation: ${esc(result.expert_validation)}</p></div>`;
}
function automaticCandidates() {
  return packet.extraction_metadata.atomic_source_checklist?.automatic_source_coverage?.verified_omission_candidates || [];
}
function renderAutomaticCoverage() {
  const coverage=packet.extraction_metadata.atomic_source_checklist?.automatic_source_coverage;
  if (!coverage) return '';
  const latest=packet.version===history.at(-1)?.version;
  return `<p class="field-help">Source-first coverage ${esc(coverage.semantic_completeness)}. ${coverage.enumeration.assertions.length} enumerated assertions; ${coverage.enumeration.unresolved_units.length} unresolved source units. These counts do not establish complete clinical recall.</p>`+
    automaticCandidates().map(c=>`<div class="question"><b>Omission candidate: ${esc(c.assertion.concept)}</b><p>${esc(c.source_verification.status)} · ${esc(c.routing)}</p>${c.assertion.spans.map(s=>`<blockquote class="quote">${esc(s.quote)}</blockquote>`).join('')}<button class="quiet-button" data-omission="${esc(c.assertion.claim_id)}" ${!latest||c.source_verification.status!=='SUPPORTED_BY_SOURCE'?'disabled':''}>Review source omission</button></div>`).join('')+
    (latest?'<button class="quiet-button" data-complete-eligible="true">Apply eligible source omissions</button>':'');
}
function openOmission(id) {
  if(!requireCurrentVersion())return;
  const candidate=automaticCandidates().find(c=>c.assertion.claim_id===id);
  if (!candidate) return;
  omissionTarget=id;semanticTarget=false;
  const a=candidate.assertion, s=a.spans[0];
  $('review-target').textContent='Source omission: '+a.concept;
  $('review-evidence').textContent='Exact source ['+s.start+':'+s.end+']';
  $('review-reason').value='';
  $('review-action').value='correct';$('review-action').disabled=true;$('correction-fields').hidden=false;
  const attributes=Object.fromEntries(['severity','duration','value','unit'].map(key=>[key,a.attributes?.[key]??null]));
  $('replacement').value=JSON.stringify({category:a.category,concept:a.concept,original_term:s.quote,
    polarity:a.polarity==='affirmed'?'present':a.polarity,temporality:a.temporality,experiencer:a.experiencer,
    attributes:Object.values(attributes).some(value=>value!==null)?attributes:null,assertion_basis:a.reporting_basis,attribution_confidence:'context_supported',
    clinical_status:a.action_state==='unknown'?null:a.action_state,evidence:{start:s.start,end:s.end,quote:s.quote}},null,2);
  setCorrectionProposal(JSON.parse($('replacement').value));
  $('review-dialog').showModal();
}
function toast(message, error=false) { $('toast').textContent=message; $('toast').classList.toggle('error',error); $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>{$('toast').hidden=true},6500); }
async function api(path, body) { if(body&&/^\/api\/cases\/.+\/(review|semantics|omission|complete-eligible|reprocess)$/.test(path)&&!canEditCurrent())throw Error('The selected saved version is not ready for editing.'); const response = await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Copilot-Token':config.csrf_token}:{},body:body?JSON.stringify(body):undefined}); const result=await response.json(); if(!response.ok)throw Error(result.error||'Request failed'); return result; }
const caseURL = () => '/api/cases/'+encodeURIComponent(packet.case_id);
async function refreshCases() { cases=await api('/api/cases'); renderCases(); }
function renderCases(){ $('cases').innerHTML=cases.map(c=>`<button class="case-button ${packet?.case_id===c.case_id?'selected':''}" data-case="${esc(c.case_id)}"><div class="case-meta"><b>${esc(c.case_id)}</b><span class="queue-dot">${c.review_required||(packet?.case_id===c.case_id&&independentCoverage().gaps.length)?'●':''}</span></div><small>${esc(c.encounter_time||'Date not documented')} · v${c.version}</small></button>`).join(''); }
async function loadCase(id, version) {
  const sequence=++caseLoadSequence,base='/api/cases/'+encodeURIComponent(id);
  requestedCaseId=id;setCaseLoading(true,false);
  try{
    const [nextPacket,nextHistory]=await Promise.all([api(base+(version?'?version='+version:'')),api(base+'/history')]);
    if(sequence!==caseLoadSequence)return false;
    const shown=await api(base+'/presentation?version='+nextPacket.version);
    if(sequence!==caseLoadSequence)return false;
    if(shown.packet_hash!==nextPacket.content_hash)throw Error('Draft view differs from the saved version. Reload the encounter.');
    packet=nextPacket;history=nextHistory;selected=packet.facts[0]?.fact_id;focusedEvidence=null;focusedRelationshipSpan=null;
    await render(shown);
    if(sequence!==caseLoadSequence)return false;
    setCaseLoading(false,true);return true;
  }catch(error){if(sequence!==caseLoadSequence)return false;setCaseLoading(false,false);throw error;}
}
async function saveRevision(path,body) {
  const sequence=caseLoadSequence,id=packet.case_id;
  const saved=await api(path,body);
  if(sequence!==caseLoadSequence)return null;
  if(!await loadCase(id,saved.version))return null;
  await refreshCases();
  return !caseLoading&&packet.content_hash===saved.content_hash?saved:null;
}
const basisNames={patient_report:'Patient reported',clinician_observation:'Clinician observed',clinician_assessment:'Clinician assessment',documented_history:'Documented history',discussion:'Discussion',unknown:'Basis unknown'};
const polarityNames={present:'Documented',absent:'Explicitly absent',uncertain:'Uncertain'};
function independentCoverage(){const value=packet?.extraction_metadata?.atomic_source_checklist;const assertions=value?.independent_source_assertions||[];return {assertions,gaps:assertions.filter(a=>a.decision!=='COVERED')};}
function renderIndependentCoverage(){
  const coverage=independentCoverage();
  if(!coverage.assertions.length)return '<p class="field-help">Independent assertion coverage not supplied. Clinical semantic completeness UNVERIFIED.</p>';
  return `<p class="field-help">Independent source assertions: ${coverage.assertions.length}. Clinical semantic completeness UNVERIFIED. COVERED records a supplied coverage decision; it does not certify medical correctness.</p>`+
    coverage.gaps.map(a=>`<div class="question"><b>${esc(a.decision)} · ${esc(a.assertion_id)}</b><p>${esc(a.text)}</p><div class="inspector-id">${esc(a.reviewer_type)} / ${esc(a.reviewer_id)} · ${esc(a.reviewer_version)}</div>${a.source_spans.map(s=>`<div class="inspector-meta">Exact source span [${esc(s.start)}:${esc(s.end)}]</div><blockquote class="quote">${esc(s.quote)}</blockquote>`).join('')}<p class="field-help">${esc(a.reason)}</p></div>`).join('');
}
async function render(prepared){
  const current=packet,sequence=caseLoadSequence;
  const shown=prepared||await api('/api/cases/'+encodeURIComponent(current.case_id)+'/presentation?version='+current.version);
  if(current!==packet||sequence!==caseLoadSequence||(!prepared&&caseLoading))return;
  if(shown.packet_hash!==packet.content_hash)throw Error('Draft view differs from the saved version. Reload the encounter.');
  presentation=shown;
  renderCases();$('breadcrumb').textContent=packet.case_id;
  $('patient-label').textContent=packet.patient_id+' / '+packet.case_id;
  $('source-label').textContent=packet.source.input_kind==='dialogue'?'Doctor–patient dialogue':'Clinical note';
  const summary=shown.summary;
  $('review-count').textContent=summary.specific_risks+' specific risks · '+summary.human_reviewed+' human-reviewed';
  $('check-count').textContent=summary.machine_supported+' source-supported · '+summary.machine_unverified+' automatic checks incomplete';
  $('note-notice').textContent='Saved source-linked draft · You can read, edit and export now. '+summary.specific_risks+' assertions have specific risk flags. Incomplete automatic checks do not establish that a statement is false.';
  $('version').innerHTML=history.map(h=>`<option value="${h.version}" ${h.version===packet.version?'selected':''}>Version ${h.version}${h.version===history.at(-1)?.version?' · latest':''}</option>`).join('');
  $('hash-label').textContent='Packet '+packet.content_hash.slice(0,18)+'… · '+packet.extraction_status;
  $('trail-count').textContent=packet.reviews.length;
  $('issues-count').textContent=packet.issues.length+independentCoverage().gaps.length;
  renderSoap();renderInspector();renderDetails();
  if(!caseLoading)setCaseLoading(false,true);
}
function presentedFact(id){return Object.values(presentation?.sections||{}).flat().find(row=>row.fact_id===id);}
function renderSoap(){
  const titles={S:'Subjective',O:'Objective',A:'Assessment',P:'Plan'};
  $('soap').innerHTML=Object.entries(titles).map(([key,title])=>`<section class="soap-section"><div class="section-header"><span class="section-letter">${key}</span><h3>${title}</h3><small>${presentation?.sections[key]?.length||0} ASSERTIONS</small></div>${(presentation?.sections[key]||[]).map(row=>`<button class="assertion-row ${selected===row.fact_id?'selected':''}" data-fact="${esc(row.fact_id)}"><div class="assertion-top"><span class="assertion-name statement-text">${esc(row.display_text||row.concept)}</span><span class="fact-reference">${esc(row.fact_id.slice(0,10))} ↗</span></div><div class="assertion-status">${row.plan_proposal?'<span>Extracted plan proposal</span>':''}${row.specific_risk?'<span class="risk-tag">Specific concern — inspect source</span>':''}${row.human_reviewed?`<span class="human-tag">${row.human_review_complete?'Human review completed':'Human decision saved'}</span>`:`<span>Human review: ${esc(row.review_status)}</span>`}<span>${row.machine_status==='SUPPORTED_BY_SOURCE'?'Machine: source-supported':row.machine_status==='INSUFFICIENT_EVIDENCE'||row.machine_status==='UNVERIFIED'?'Machine: check incomplete':'Machine: '+esc(row.machine_status)}</span></div>${row.section_note?`<div class="field-help">${esc(row.section_note)}</div>`:''}${(row.presentation_notes||[]).map(note=>`<div class="field-help">${esc(note)}</div>`).join('')}<div class="draft-citations">Evidence: ${row.evidence_ids.map(esc).join(', ')}</div></button>`).join('')||'<p class="empty-section">Not documented in the accepted extraction.</p>'}</section>`).join('');
  $('soap').innerHTML+=renderRelationshipProposals();
}
function renderRelationshipProposals() {
  const rows=presentation?.relationship_proposals||[];
  if(!rows.length)return '';
  const endpoint=e=>e.fact_id?`<button class="text-button" data-fact="${esc(e.fact_id)}">${esc(e.original_concept||'Unnormalized assertion')} · input ${esc(e.input_index)} ↗</button>`:`<span>Unresolved input ${esc(e.input_index)}</span>`;
  return `<section class="soap-section relationship-proposals"><div class="section-header"><h3>Relationship proposals</h3><small>${rows.length} PROPOSALS</small></div><p class="field-help">Original extraction links; clinical meaning is unverified. Inspect both endpoints and the cited source.</p>${rows.map(row=>`<div class="question" data-relationship="${esc(row.relationship_id)}"><div>${endpoint(row.from)} → <b>${esc(row.relation||'Unspecified relation')}</b> → ${endpoint(row.to)}</div><p class="field-help">${esc(row.relationship_id)} · ${esc(row.status)} · ${esc(row.structural_status)} · Adopted in saved SOAP: ${row.adopted_in_soap?'yes':'no'}</p>${row.structural_concern?`<p class="risk-tag">${esc(row.structural_concern)}</p>`:''}${row.citations.map(span=>`<blockquote class="quote">${esc(span.quote)}</blockquote><p class="field-help">${esc(span.document_id||packet.source.document_id)} · ${esc(span.speaker_label||'Unlabeled source')} · characters ${esc(span.start)}–${esc(span.end)} · ${span.source_match?'Exact source match':'Source match unresolved'}</p>${span.source_match?`<button class="text-button" data-relationship-span="${esc(span.span_id)}">Locate relationship in original source ↗</button>`:''}`).join('')}</div>`).join('')}</section>`;
}
function locateRelationshipSpan(id) {
  const span=(presentation?.relationship_proposals||[]).flatMap(row=>row.citations).find(span=>span.span_id===id&&span.source_match);
  if(!span)return;
  focusedRelationshipSpan={...span,evidence_id:span.span_id};focusedEvidence=span.span_id;activeTab='source';renderDetails();
  const mark=$('detail-panel').querySelector('[data-source-evidence="'+CSS.escape(span.span_id)+'"]');
  if(mark){mark.scrollIntoView({block:'center',behavior:'instant'});mark.focus({preventScroll:true});}
}
function locateEvidence(id) {
  focusedRelationshipSpan=null;focusedEvidence=id;activeTab='source';
  const target=packet.facts.find(f=>f.evidence_ids.includes(id));
  if(target&&target.fact_id!==selected){selected=target.fact_id;renderSoap();renderInspector();}
  renderDetails();
  const mark=$('detail-panel').querySelector('[data-source-evidence="'+CSS.escape(id)+'"]');
  if(mark){mark.scrollIntoView({block:'center',behavior:'instant'});mark.focus({preventScroll:true});}
}
function evidenceMarkup(e) {
  const chars=Array.from(packet.source.text);
  const context=chars.slice(e.context_start,e.context_end).join('');
  return `<section class="evidence-passage"><div class="inspector-meta"><span>Citation ${e.citation_order}${e.citation_order===1?' · Primary':''} · ${esc(e.evidence_id)}</span><span>Record ${esc(e.record_orders?.join(', ')||'unknown')}</span></div><p class="field-help">Original speaker: ${esc(e.raw_speaker_labels?.filter(Boolean).join(' / ')||'Unlabeled source')} · Indexed turn: ${esc(e.turn_id)}</p><blockquote class="quote">${esc(e.quote)}</blockquote><div class="verified-line">Exact source match · characters ${e.start}–${e.end} · lines ${e.line_start}–${e.line_end}</div><button class="text-button" data-locate-evidence="${esc(e.evidence_id)}">Locate in original source ↗</button><details class="evidence-context"><summary>Expand adjacent original records</summary><p class="field-help">Original record order; speaker labels are retained, not independently verified roles. Context is not an additional citation.</p><pre class="context-text">${esc(context)}</pre></details></section>`;
}
function renderInspector(){
  const f=packet.facts.find(f=>f.fact_id===selected);
  if(!f){$('inspector').innerHTML='<div class="inspector-body"><p>No accepted assertions. Inspect extraction questions below.</p></div>';return;}
  const evidenceById=new Map((presentation.source_navigation?.evidence||packet.evidence).map(e=>[e.evidence_id,e]));
  const evidences=f.evidence_ids.map((id,index)=>evidenceById.has(id)?{...evidenceById.get(id),citation_order:index+1}:null).filter(Boolean).sort((a,b)=>a.start-b.start||a.end-b.end);
  const questions=packet.issues.filter(i=>i.fact_ids.includes(f.fact_id));
  const historical=packet.version!==history.at(-1)?.version;
  const row=presentedFact(f.fact_id), event=row?.fields.find(field=>field.label==='Event time (proposal)')?.value;
  $('inspector').innerHTML=`<div class="inspector-body"><h3 class="inspector-title">${esc(f.assertion.concept||'Source assertion')}</h3><div class="inspector-id">${esc(f.fact_id)}</div><p class="field-help">Encounter date: ${esc(packet.source.encounter_time||'Not documented')}<br>Event time in this assertion: ${esc(event||'Not asserted')}<br>Passages follow the original record order. Citation numbers and the primary marker retain the selected citation order.</p>${evidences.map(evidenceMarkup).join('')}<p class="evidence-note">Read cited questions and answers together. Exact matching locates the text; it does not establish clinical correctness.</p><details><summary>Retained assertion fields</summary><p class="field-help">${row?.fields.map(field=>`${esc(field.label)}: ${esc(field.value)}`).join(' · ')||''}</p></details>${questions.map(q=>`<div class="question ${q.severity==='high'?'specific-risk':'check-note'}"><b>${esc(q.code.replaceAll('_',' ').toUpperCase())}</b>${esc(q.question)}${(q.evidence_ids.length?q.evidence_ids:f.evidence_ids).map(id=>`<button class="text-button" data-locate-evidence="${esc(id)}">Locate ${esc(id)} ↗</button>`).join('')}</div>`).join('')}${verificationPanel(f)}<div class="inspector-actions"><button class="primary-button" id="open-review" ${historical?'disabled':''}>Review assertion</button><button class="quiet-button" id="ai-task">Export review context ↗</button>${packet.extraction_metadata.soap_projection_version==='soap/v6'?`<button class="quiet-button" id="edit-semantics" ${historical?'disabled':''}>Edit timing & attributes</button>`:''}</div>${historical?'<p class="field-help">Historical version. Select latest to record a review.</p>':''}</div>`;
  $('open-review').onclick=openReview;$('ai-task').onclick=()=>downloadTask(f.fact_id);
  if($('edit-semantics'))$('edit-semantics').onclick=openSemantics;
  $('inspector').querySelectorAll('[data-locate-evidence]').forEach(button=>button.onclick=()=>locateEvidence(button.dataset.locateEvidence));
}
function sourceTextMarkup(spans){
  const chars=Array.from(packet.source.text), boundaries=[...new Set([0,chars.length,...spans.flatMap(e=>[e.start,e.end])])].sort((a,b)=>a-b);
  return boundaries.slice(0,-1).map((start,i)=>{const end=boundaries[i+1],text=esc(chars.slice(start,end).join(''));const active=spans.filter(e=>e.start<=start&&end<=e.end);if(!active.length)return text;const chosen=active.find(e=>e.evidence_id===focusedEvidence)||active[0];return `<mark tabindex="-1" data-source-evidence="${esc(chosen.evidence_id)}" title="${esc(active.map(e=>e.evidence_id).join(', '))}">${text}</mark>`;}).join('');
}
function renderDetails(){for(const tab of ['source','trail','issues']){$(tab+'-tab').classList.toggle('active',activeTab===tab);$(tab+'-tab').setAttribute('aria-selected',String(activeTab===tab));}if(activeTab==='source'){const f=packet.facts.find(f=>f.fact_id===selected);const spans=[...packet.evidence.filter(e=>f?.evidence_ids.includes(e.evidence_id)||e.evidence_id===focusedEvidence),...(focusedRelationshipSpan?[focusedRelationshipSpan]:[])].sort((a,b)=>a.start-b.start);const content=sourceTextMarkup(spans);$('detail-panel').innerHTML=`<div class="source-head"><span>${esc(packet.source.document_id)} · ${esc(packet.source.encounter_time||'Time not documented')}</span><code>SHA256 ${esc(packet.source.sha256.slice(0,16))}…</code></div><pre class="source-text">${content}</pre>`;const mark=focusedEvidence?$('detail-panel').querySelector('[data-source-evidence="'+CSS.escape(focusedEvidence)+'"]'):$('detail-panel').querySelector('mark');if(mark){const pre=mark.parentElement;pre.scrollTop=Math.max(0,mark.offsetTop-pre.offsetTop-30);}}else if(activeTab==='trail'){$('detail-panel').innerHTML=packet.reviews.length?packet.reviews.map(r=>`<div class="trail-row"><div><strong>Version ${r.applied_version}</strong><small>${esc(r.reviewer.reviewer_type)} / ${esc(r.reviewer.reviewer_id)}</small><small>${esc(r.reviewer.version)}</small></div><div><strong>${esc(r.action)} · ${esc(r.fact_id)}</strong><p>${esc(r.reason)}</p><code>Evidence: ${esc(r.evidence_ids.join(', '))}</code>${r.action==='correct'?`<details><summary>Before / after assertion</summary><pre class="code-input">${esc(JSON.stringify({before:r.before,after:r.after},null,2))}</pre></details>`:''}</div></div>`).join(''):'<p class="field-help">No reviews recorded. This draft is saved; a signature is not required to continue.</p>';$('detail-panel').innerHTML+=(packet.extraction_metadata.program_reprocessing_events||[]).map(e=>`<div class="trail-row"><div><strong>Version ${e.applied_version}</strong><small>Program / ${esc(e.profile_version)}</small></div><div><strong>Source reprocessing</strong><p>${esc(e.reason)}</p><p class="field-help">Zero model calls. Original proposals retained. No human approval created.</p><details><summary>Processing provenance</summary><pre class="code-input">${esc(JSON.stringify(e,null,2))}</pre></details></div></div>`).join('');}else{$('detail-panel').innerHTML=packet.issues.length?packet.issues.map(i=>`<div class="question"><b>${esc(i.code.replaceAll('_',' ').toUpperCase())}</b>${esc(i.question)}<div class="inspector-id">${esc(i.fact_ids.join(', '))}</div>${i.fact_ids.map(id=>`<button class="text-button" data-question-fact="${esc(id)}">Inspect assertion ↗</button>`).join('')}${i.evidence_ids.map(id=>`<button class="text-button" data-locate-evidence="${esc(id)}">Locate cited source ↗</button>`).join('')}</div>`).join(''):'<p class="field-help">No automatic discrepancy flags. This is not clinical certification.</p>';$('detail-panel').innerHTML+=renderIndependentCoverage()+renderAutomaticCoverage();if(packet.relationships.length)$('detail-panel').innerHTML+=`<p class="field-help">${packet.relationships.length} relationship proposals are shown below the SOAP assertions with their original endpoints and citations; their clinical meaning is unverified.</p>`;if(packet.rejected_facts.length)$('detail-panel').innerHTML+=`<details><summary>${packet.rejected_facts.length} rejected proposals</summary><pre class="code-input">${esc(JSON.stringify(packet.rejected_facts,null,2))}</pre></details>`;}}
function download(name,content,type='application/json'){const url=URL.createObjectURL(new Blob([content],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function downloadTask(fact){try{const task=await api(caseURL()+'/review-task?version='+packet.version+(fact?'&fact_id='+encodeURIComponent(fact):''));download(packet.case_id+'-review-task.json',JSON.stringify(task,null,2));toast('Reviewer task exported. No model call was made.');}catch(e){toast(e.message,true)}}
function openReview(){if(!requireCurrentVersion())return;omissionTarget=null;semanticTarget=false;$('review-action').disabled=false;const f=packet.facts.find(f=>f.fact_id===selected);$('review-target').textContent=f.assertion.concept||f.fact_id;$('review-evidence').textContent=f.evidence_ids.join(', ');$('review-reason').value='';setCorrectionProposal(f.assertion);$('review-action').value='accept';$('correction-fields').hidden=true;$('review-dialog').showModal();}
function openSemantics(){
  if(!requireCurrentVersion())return;
  openReview(); semanticTarget=true;
  const claim=packet.extraction_metadata.evidence_verification?.assertions.find(r=>r.fact_id===selected)?.proposed_claim;
  const r=packet.extraction_metadata.clinical_semantics_v2?.find(r=>r.fact_id===selected);
  const value=claim?{version:'clinical-fact-semantics/2',frequency:claim.attributes?.frequency??null,event_time:claim.event_time??null,duration:claim.attributes?.duration??null,action_state:claim.action_state??'unknown',completion_scope:claim.completion_scope??null,assertion_basis:claim.reporting_basis??'unknown',action_type:claim.action_type??null}:r?.semantics;
  setCorrectionProposal(value||{version:'clinical-fact-semantics/2',frequency:null,event_time:null,duration:null,action_state:'unknown',completion_scope:null,assertion_basis:'unknown',action_type:null},true);
  $('review-action').value='correct';$('review-action').disabled=true;$('correction-fields').hidden=false;
  $('review-target').textContent+=' — timing & attributes';
}
$('review-action').onchange=()=>{$('correction-fields').hidden=$('review-action').value!=='correct';};
async function submitOmission(e) {
  if(!requireCurrentVersion())return;
  const button=e.submitter;button.disabled=true;
  try {
    const saved=await saveRevision(caseURL()+'/omission',{base_version:packet.version,candidate_claim_id:omissionTarget,
      reason:$('review-reason').value,assertion:correctionValue(),
      reviewer:{reviewer_id:$('reviewer-id').value,reviewer_type:$('review-type').value,version:$('reviewer-version').value}});
    if(!saved)return;
    omissionTarget=null;$('review-action').disabled=false;$('review-dialog').close();
    toast('Source correction saved as version '+saved.version+'.');
  } catch(error) {toast(error.message,true);} finally {button.disabled=!canEditCurrent();}
}
$('detail-panel').onclick=async e=>{
  const citation=e.target.closest('[data-locate-evidence]');
  if(citation){locateEvidence(citation.dataset.locateEvidence);return;}
  const question=e.target.closest('[data-question-fact]');
  if(question){selected=question.dataset.questionFact;focusedEvidence=null;activeTab='source';renderSoap();renderInspector();renderDetails();$('inspector').scrollIntoView({block:'start'});return;}
  const omission=e.target.closest('[data-omission]');
  if(omission){openOmission(omission.dataset.omission);return;}
  const completion=e.target.closest('[data-complete-eligible]');
  if(!completion||!requireCurrentVersion())return;completion.disabled=true;
  try{const previous=packet.version;const saved=await saveRevision(caseURL()+'/complete-eligible',{base_version:packet.version});
    if(!saved)return;
    toast(saved.version===previous?'No candidate meets the calibrated automatic processing boundary.':'Saved source corrections through version '+packet.version+'.');
  }catch(error){toast(error.message,true);}finally{completion.disabled=!canEditCurrent();}
};
$('review-form').onsubmit=async e=>{e.preventDefault();if(!requireCurrentVersion())return;if(omissionTarget)return submitOmission(e);const f=packet.facts.find(f=>f.fact_id===selected);const submit=e.submitter;submit.disabled=true;try{const body={base_version:packet.version,fact_id:f.fact_id,action:$('review-action').value,reason:$('review-reason').value,evidence_ids:f.evidence_ids,reviewer:{reviewer_id:$('reviewer-id').value,reviewer_type:$('review-type').value,version:$('reviewer-version').value}};if(semanticTarget){delete body.action;body.semantics=correctionValue();}else if(body.action==='correct')body.replacement=correctionValue();const saved=await saveRevision(caseURL()+(semanticTarget?'/semantics':'/review'),body);if(!saved)return;semanticTarget=false;$('review-action').disabled=false;$('review-dialog').close();toast('Saved version '+saved.version+'. Original source preserved.');}catch(err){toast(err.message,true)}finally{submit.disabled=!canEditCurrent();}};
$('cases').onclick=e=>{const b=e.target.closest('[data-case]');if(b)loadCase(b.dataset.case).catch(e=>toast(e.message,true));};
$('soap').onclick=e=>{const span=e.target.closest('[data-relationship-span]');if(span){locateRelationshipSpan(span.dataset.relationshipSpan);return;}const b=e.target.closest('[data-fact]');if(b){selected=b.dataset.fact;focusedEvidence=null;focusedRelationshipSpan=null;activeTab='source';renderSoap();renderInspector();renderDetails();}};
$('version').onchange=()=>loadCase(requestedCaseId||packet.case_id,+$('version').value).catch(e=>toast(e.message,true));
for(const tab of ['source','trail','issues'])$(tab+'-tab').onclick=()=>{activeTab=tab;renderDetails();};
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
$('reprocess').onclick=()=>{if(!requireCurrentVersion())return;$('reprocess-reason').value='';$('reprocess-dialog').showModal();};
$('reprocess-form').onsubmit=async e=>{e.preventDefault();if(!requireCurrentVersion())return;const b=e.submitter;b.disabled=true;try{const saved=await saveRevision(caseURL()+'/reprocess',{base_version:packet.version,reason:$('reprocess-reason').value});if(!saved)return;$('reprocess-dialog').close();toast('Program revision saved. No model call or human approval.');}catch(error){toast(error.message,true)}finally{b.disabled=!canEditCurrent();}};
$('export-json').onclick=()=>download(packet.case_id+'-v'+packet.version+'.json',JSON.stringify(packet,null,2));
async function exportMarkdown(draft){try{const response=await fetch(caseURL()+'/markdown?version='+packet.version+(draft?'&view=draft':''));if(!response.ok)throw Error('Export failed');download(packet.case_id+'-v'+packet.version+(draft?'-soap-draft':'-full-audit')+'.md',await response.text(),'text/markdown');}catch(e){toast(e.message,true)}}
$('export-md').onclick=()=>exportMarkdown(true);
$('export-audit-md').onclick=()=>exportMarkdown(false);
let importedBundle;
let newModeHelpBaseline=$('new-mode-help').textContent;
function resetNewModeHelp(){$('new-mode-help').textContent=newModeHelpBaseline;}
$('new-case').onclick=()=>{importedBundle=undefined;$('new-form').reset();resetNewModeHelp();$('new-dialog').showModal();};
$('bundle-file').onchange=async()=>{importedBundle=undefined;try{const bundle=JSON.parse(await $('bundle-file').files[0].text());$('new-case-id').value=bundle.case_id;$('new-patient-id').value=bundle.patient_id;$('new-kind').value=bundle.source.input_kind;$('new-date').value=bundle.source.encounter_time?.slice(0,10)||'';$('new-text').value=bundle.source.text;$('new-extraction').value=JSON.stringify(bundle.extraction,null,2);importedBundle=bundle;resetNewModeHelp();}catch(e){toast('Invalid bundle: '+e.message,true)}};
$('new-form').onsubmit=async e=>{
  e.preventDefault();$('create-button').disabled=true;
  try{
    let created;
    const caseId=$('new-case-id').value.trim(),patientId=$('new-patient-id').value.trim(),text=$('new-text').value;
    if($('new-extraction').value.trim()){
      const extraction=JSON.parse($('new-extraction').value);
      if(importedBundle&&(patientId!==importedBundle.patient_id||text!==importedBundle.source.text||
          extraction.document_id!==importedBundle.source.document_id||$('new-kind').value!==importedBundle.source.input_kind||
          $('new-date').value!==(importedBundle.source.encounter_time?.slice(0,10)||'')))
        throw Error('Imported source identity changed. Create a separate source or use the review/correction workflow.');
      let source;
      if(importedBundle)source={...importedBundle.source};
      else{
        const bytes=new TextEncoder().encode(text);
        const sourceHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(b=>b.toString(16).padStart(2,'0')).join('');
        source={document_id:extraction.document_id,text,sha256:sourceHash,input_kind:$('new-kind').value,encounter_time:$('new-date').value||null,origin:'browser_supplied'};
      }
      const atoms=importedBundle&&Object.prototype.hasOwnProperty.call(importedBundle,'atomic_source_assertions')?importedBundle.atomic_source_assertions:[];
      created=await api('/api/cases',{case_id:caseId,patient_id:patientId,source,extraction,atomic_source_assertions:atoms,origin:importedBundle?.origin||'browser_supplied'});
    }else{
      if(importedBundle)throw Error('Imported bundles require their source-linked extraction. Create a separate source or use the review/correction workflow.');
      if(!config.live_enabled)throw Error('This workspace is in offline replay mode. Start the product launcher with live extraction enabled to process pasted text, or use Advanced import for a saved extraction.');
      created=await api('/api/extract',{case_id:caseId,patient_id:patientId,text,input_kind:$('new-kind').value,encounter_time:$('new-date').value||null});
    }
    await refreshCases();await loadCase(created.case_id);$('new-dialog').close();toast('Encounter saved · '+created.extraction_status);
  }catch(err){$('new-mode-help').textContent=err.message;toast(err.message,true)}finally{$('create-button').disabled=false;}
};
async function comparisonVersions(side) {
  const rows=await api('/api/cases/'+encodeURIComponent($('compare-'+side).value)+'/history');
  $('compare-'+side+'-version').innerHTML=rows.map(h=>`<option value="${h.version}">Version ${h.version}</option>`).join('');
  $('compare-'+side+'-version').value=String(rows.at(-1).version);
}
$('compare-before').onchange=()=>comparisonVersions('before').catch(e=>toast(e.message,true));
$('compare-after').onchange=()=>comparisonVersions('after').catch(e=>toast(e.message,true));
$('compare').onclick=async()=>{try{
  const options=cases.map(c=>`<option value="${esc(c.case_id)}">${esc(c.case_id)} · ${esc(c.patient_id)} · ${esc(c.encounter_time||'unknown date')}</option>`).join('');
  $('compare-before').innerHTML=options;$('compare-after').innerHTML=options;$('compare-before').value=packet.case_id;
  const other=cases.find(c=>c.patient_id===packet.patient_id&&c.case_id!==packet.case_id);
  $('compare-after').value=other?other.case_id:packet.case_id;
  await Promise.all([comparisonVersions('before'),comparisonVersions('after')]);
  $('compare-before-version').value=String(packet.version);
  $('comparison-result').innerHTML='';$('compare-dialog').showModal();
}catch(e){toast(e.message,true)}};
function comparisonSide(c,side) {
  const proposals=c[side+'_effective_proposals'];
  if(!proposals)return c[side].map(f=>esc([f.polarity,f.temporality,f.clinical_status].filter(Boolean).join(' · '))).join('<br>')||'Not documented';
  return proposals.map(row=>`<div><code>${esc(row.fact_id)}</code><p>${Object.entries(row.values).filter(([key,value])=>value!==null&&value!==undefined&&key!=='concept').map(([key,value])=>`${esc(key.replace('attributes.','').replaceAll('_',' '))}: ${esc(value)}`).join(' · ')}</p><small>Evidence: ${row.evidence_ids.map(esc).join(', ')}</small></div>`).join('')||'Not documented';
}
$('run-compare').onclick=async()=>{try{
  const before=$('compare-before').value,after=$('compare-after').value;
  const query='/api/compare?before='+encodeURIComponent(before)+'&after='+encodeURIComponent(after)+'&before_version='+$('compare-before-version').value+'&after_version='+$('compare-after-version').value;
  const d=await api(query);
  $('comparison-result').innerHTML=`<p class="field-help">${esc(d.before.case_id)} v${d.before.version} → ${esc(d.after.case_id)} v${d.after.version}</p>`+d.changes.map(c=>`<div class="comparison-item"><b>${esc(c.concept)}</b><span class="comparison-change">${esc(c.change.replaceAll('_',' '))}</span><p class="field-help">${esc(c.change_kind||'')} · Source: ${esc(c.source_support_status)} · ${esc(c.documentation_comparison_status||'UNVERIFIED')}.</p><p class="field-help">${esc((c.comparison_scope?.uncertainty||[]).join(' '))}</p>${c.dimension_changes?.length?`<p>Changed fields: ${c.dimension_changes.map(x=>esc(x.dimension.replace('attributes.','').replaceAll('_',' '))).join(', ')}</p>`:''}<div class="comparison-states"><div>${comparisonSide(c,'before')}</div><div>${comparisonSide(c,'after')}</div></div></div>`).join('');
}catch(e){toast(e.message,true)}};
async function init(){try{config=await api('/api/config');$('mode-label').textContent=config.live_enabled?'Live extraction available':'Offline · No model calls';if(config.live_enabled){$('new-mode-help').textContent='Paste the source and save. Luna will extract once; the source-linked draft and request record are saved automatically.';$('create-button').textContent='Extract & save draft';}else{$('new-mode-help').textContent='Offline replay workspace. Pasted text requires live extraction; Advanced import can replay saved source-linked facts.';$('create-button').textContent='Import saved draft';}newModeHelpBaseline=$('new-mode-help').textContent;await refreshCases();if(cases.length)await loadCase(cases[0].case_id);else $('patient-label').textContent='Create your first encounter';}catch(e){toast(e.message,true)}}
init();
