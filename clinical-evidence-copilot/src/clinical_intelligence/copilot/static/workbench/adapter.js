// Same-origin HTTP boundary. This module never supplies invented clinical data.
export class WorkbenchAPI {
  constructor(fetcher = globalThis.fetch.bind(globalThis)) { this.fetcher = fetcher; this.config = {}; }
  async request(path, body) {
    const options = {method: body === undefined ? 'GET' : 'POST', credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}};
    if (body !== undefined) {
      if (!this.config.csrf_token) throw new Error('The local write token is unavailable. Reload before saving.');
      Object.assign(options.headers, {'Content-Type':'application/json','X-Copilot-Token':this.config.csrf_token});
      options.body = JSON.stringify(body);
    }
    let response;
    try { response = await this.fetcher(path, options); }
    catch (_) { throw new Error('The local server could not be reached. Your unsaved input remains on this page.'); }
    let result;
    try { result = await response.json(); }
    catch (_) { throw new Error(`The server returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const detail = result.error || result.detail || 'Request failed';
      const error = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      error.status = response.status; error.payload = result; throw error;
    }
    return result;
  }
  async initialize() { this.config = await this.request('/api/config'); return this.config; }
  patients() { return this.request('/ui/patients'); }
  createPatient(body) { return this.request('/ui/patients', body); }
  path(patient, suffix = '') { return `/ui/patients/${encodeURIComponent(patient)}${suffix}`; }
  workspace(patient) { return this.request(this.path(patient,'/workspace')); }
  files(patient, files) { return this.request(this.path(patient,'/files'), {files}); }
  soap(patient, encounter) { return this.request(this.path(patient,`/encounters/${encodeURIComponent(encounter)}/soap`)); }
  evidence(patient, ref) { return this.request(this.path(patient,`/evidence/${encodeURIComponent(ref.case_id)}`) + (ref.packet_version != null ? `?version=${encodeURIComponent(ref.packet_version)}` : '')); }
  capabilities(patient) { return this.request(this.path(patient,'/query-capabilities')); }
  query(patient, query) { return this.request(this.path(patient,'/queries'), query); }
  correction(patient, caseId, factId, body) { return this.request(this.path(patient,`/facts/${encodeURIComponent(caseId)}/${encodeURIComponent(factId)}/corrections`), body); }
  polish(patient, encounter, evidenceVersion) { return this.request(this.path(patient,'/soap/polish'), {encounter_id:encounter,evidence_version:evidenceVersion,request_id:requestId(),allow_model:true,model:'gpt-6-luna'}); }
  careflow(patient, suffix = '', body) { return this.request(this.path(patient,'/careflow/requests'+suffix), body); }
}
export function requestId() { return globalThis.crypto?.randomUUID?.() || `workbench-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
export function rows(value) { return Array.isArray(value) ? value : []; }
export function capabilitiesList(value) {
  const list = value?.families || value?.supported_families || value?.query_families || value?.queries || [];
  return Array.isArray(list) ? list.map(item => typeof item === 'string' ? {family:item} : item) : Object.entries(list).map(([family, spec])=>({family,...spec}));
}
export function sourceRefs(item) {
  if (!item || typeof item !== 'object') return [];
  if (item.case_id && (Number.isInteger(item.start) || item.fact_id || item.document_id)) return [item];
  return rows(item.source_refs || item.refs || item.evidence || item.citations || item.record?.source_refs).filter(ref => ref && typeof ref === 'object');
}
// All offsets in saved packets are Unicode code points, not JS UTF-16 units.
export function sourceSlice(text, start, end) { return Array.from(String(text || '')).slice(start, end).join(''); }
export function describe(value) {
  if (value == null) return 'Not documented';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(describe).join('; ');
  const preferred = ['answer','text','display_text','statement','description','message','reason','label','result','value'];
  for (const key of preferred) if (value[key] != null) {
    const text = describe(value[key]);
    return value.unit ? `${text} ${value.unit}` : text;
  }
  return Object.entries(value).filter(([key])=>!['source_refs','evidence','refs','citations'].includes(key)).map(([key,item])=>`${key.replaceAll('_',' ')}: ${describe(item)}`).join(' · ');
}
