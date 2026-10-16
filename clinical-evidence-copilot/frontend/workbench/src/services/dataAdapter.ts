/** Real same-origin workbench API. Saved clinical data is never synthesized. */
import type { RawRecord, SourceRef, WorkbenchConfig, UploadFile } from '../types/clinical.ts';

export interface ApiEndpointSpec {
  method: 'GET' | 'POST'; path: string; source: 'CURRENT_API'; status: 'LIVE_READY'; description: string;
}
export const API_CATALOG: ApiEndpointSpec[] = [
  ['GET', '/api/config', 'Local runtime capabilities and CSRF token.'],
  ['GET', '/ui/patients', 'Registered patients; demographics are not inferred.'],
  ['GET', '/ui/patients/:patient/workspace', 'Explicit encounter/document bindings, versions, jobs and capabilities.'],
  ['GET', '/ui/patients/:patient/encounters/:encounter/soap', 'Saved SOAP with all original source references.'],
  ['GET', '/ui/patients/:patient/evidence/:case?version=:version', 'Immutable packet, complete original source, presentation and true revision history.'],
  ['POST', '/ui/patients/:patient/files', 'Persistent per-file jobs; failed or uncertain calls are not automatically retried.'],
  ['POST', '/ui/patients/:patient/queries', 'Deterministic calculations and source traces; natural-language interpretation requires explicit extra Luna opt-in.'],
  ['POST', '/ui/patients/:patient/facts/:case/:fact/corrections', 'Version-checked source-backed corrections and shared-request synchronization.'],
  ['GET', '/ui/patients/:patient/careflow/requests', 'Actual material requests and shared-evidence state.'],
  ['POST', '/ui/patients/:patient/careflow/requests/:case/:action', 'Receive originals, sync saved evidence or recalculate.'],
  ['POST', '/ui/patients/:patient/soap/polish', 'Explicit extra Luna call to organize selected saved key point IDs without changing clinical wording.'],
].map(([method, path, description]) => ({method, path, description, source: 'CURRENT_API', status: 'LIVE_READY'})) as ApiEndpointSpec[];

export class WorkbenchRequestError extends Error { status?: number; payload?: unknown; }

export class ClinicalDataAdapter {
  config: WorkbenchConfig = {};
  private fetcher: typeof fetch;
  constructor(fetcher: typeof fetch = globalThis.fetch.bind(globalThis)) { this.fetcher = fetcher; }

  async request<T = RawRecord>(path: string, body?: unknown): Promise<T> {
    if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Only same-origin API paths are supported.');
    const headers: Record<string, string> = {Accept: 'application/json'};
    const options: RequestInit = {method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers};
    if (body !== undefined) {
      if (!this.config.csrf_token) throw new Error('The local write token is unavailable. Reload before saving.');
      headers['Content-Type'] = 'application/json'; headers['X-Copilot-Token'] = this.config.csrf_token;
      options.body = JSON.stringify(body);
    }
    let response: Response;
    try { response = await this.fetcher(path, options); }
    catch { throw new Error('The local server could not be reached. Unsaved input has not been saved; it remains on this page.'); }
    let result: unknown;
    try { result = await response.json(); }
    catch { throw new Error(`The server returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const detail = (result as RawRecord | null)?.error || (result as RawRecord | null)?.detail || 'Request failed';
      const error = new WorkbenchRequestError(typeof detail === 'string' ? detail : JSON.stringify(detail));
      error.status = response.status; error.payload = result; throw error;
    }
    // Keep every returned field, source reference, five-state result and hash.
    return result as T;
  }

  async initialize(): Promise<WorkbenchConfig> { this.config = await this.request<WorkbenchConfig>('/api/config'); return this.config; }
  path(patient: string, suffix = '') { return `/ui/patients/${encodeURIComponent(patient)}${suffix}`; }
  getPatients() { return this.request('/ui/patients'); }
  createPatient(body: RawRecord) { return this.request('/ui/patients', body); }
  getWorkspace(patient: string) { return this.request(this.path(patient, '/workspace')); }
  getSoap(patient: string, encounter: string) { return this.request(this.path(patient, `/encounters/${encodeURIComponent(encounter)}/soap`)); }
  getEvidence(patient: string, ref: SourceRef | RawRecord) {
    if (!ref.case_id) throw new Error('A saved case identity is required to open original evidence.');
    return this.request(this.path(patient, `/evidence/${encodeURIComponent(ref.case_id)}`) + (ref.packet_version == null ? '' : `?version=${encodeURIComponent(ref.packet_version)}`));
  }
  getHistory(caseId: string) { return this.request<RawRecord[] | RawRecord>(`/api/cases/${encodeURIComponent(caseId)}/history`); }
  getPacket(caseId: string, version?: number) { return this.request(`/api/cases/${encodeURIComponent(caseId)}${version == null ? '' : `?version=${encodeURIComponent(version)}`}`); }
  audit(patient: string) { return this.request(this.path(patient, '/audit')); }
  capabilities(patient: string) { return this.request(this.path(patient, '/query-capabilities')); }
  files(patient: string, files: UploadFile[] | RawRecord[]) { return this.request(this.path(patient, '/files'), {files}); }
  correction(patient: string, caseId: string, factId: string, body: RawRecord) {
    return this.request(this.path(patient, `/facts/${encodeURIComponent(caseId)}/${encodeURIComponent(factId)}/corrections`), body);
  }
  query(patient: string, body: RawRecord) {
    if ('question' in body) {
      this.requireLive('Question interpretation');
      if (body.allow_model !== true) throw new Error('Question interpretation requires explicit extra Luna opt-in.');
      if (body.model != null && body.model !== 'gpt-6-luna') throw new Error('The product runtime supports gpt-6-luna only.');
    }
    return this.request(this.path(patient, '/queries'), body);
  }
  interpretQuestion(patient: string, question: string, allowModel: boolean) {
    if (allowModel !== true) throw new Error('Question interpretation requires explicit extra Luna opt-in.');
    return this.query(patient, {question, allow_model: true, model: 'gpt-6-luna', request_id: requestId()});
  }
  polish(patient: string, encounter: string, evidenceVersion: string, statementIds?: string[]) {
    this.requireLive('Key point organization');
    return this.request(this.path(patient, '/soap/polish'), {encounter_id: encounter, evidence_version: evidenceVersion, request_id: requestId(), allow_model: true, model: 'gpt-6-luna', ...(statementIds===undefined?{}:{statement_ids:statementIds})});
  }
  careflow(patient: string, suffix = '', body?: RawRecord) {
    if (suffix && (!suffix.startsWith('/') || suffix.includes('?') || suffix.includes('#') || suffix.split('/').includes('..'))) throw new Error('Invalid CareFlow request path.');
    return this.request(this.path(patient, '/careflow/requests' + suffix), body);
  }
  getCareflowRequests(patient: string) { return this.careflow(patient); }
  getCareflowRequest(patient: string, caseId: string) { return this.careflow(patient, `/${encodeURIComponent(caseId)}`); }
  createCareflowRequest(patient: string, body: RawRecord) { return this.careflow(patient, '', body); }
  addCareflowDocument(patient: string, caseId: string, body: RawRecord) { return this.careflow(patient, `/${encodeURIComponent(caseId)}/documents`, body); }
  recalculateCareflow(patient: string, caseId: string, body: RawRecord) { return this.careflow(patient, `/${encodeURIComponent(caseId)}/recalculate`, body); }
  syncCareflow(patient: string, caseId: string, body: RawRecord) { return this.careflow(patient, `/${encodeURIComponent(caseId)}/sync-shared`, body); }
  private requireLive(operation: string) {
    if (this.config.live_enabled !== true) throw new Error(`${operation} is unavailable in offline mode. Saved evidence remains available.`);
  }
}

export function requestId() { return globalThis.crypto?.randomUUID?.() || `workbench-${Date.now()}-${Math.random().toString(36).slice(2)}`; }
export function rows<T = RawRecord>(value: unknown): T[] { return Array.isArray(value) ? value : []; }
export function capabilitiesList(value: RawRecord | null | undefined): RawRecord[] {
  const list = value?.families || value?.supported_families || value?.query_families || value?.queries || [];
  return Array.isArray(list) ? list.map(item => typeof item === 'string' ? {family: item} : item)
    : Object.entries(list).map(([family, spec]) => ({family, ...(spec as RawRecord)}));
}
export function sourceRefs(item: RawRecord | null | undefined): SourceRef[] {
  if (!item || typeof item !== 'object') return [];
  // A SOAP statement also has case_id/fact_id. Its actual source_refs must take
  // precedence over treating that containing statement as an individual span.
  for (const value of [item.all_refs, item.source_refs, item.refs, item.evidence, item.citations, item.record?.source_refs]) {
    if (Array.isArray(value) && value.length) return value.filter(ref => ref && typeof ref === 'object');
  }
  if (item.case_id && (Number.isInteger(item.start) || item.fact_id || item.document_id)) return [item as SourceRef];
  return [];
}
/** Unicode code points, end exclusive; no UTF-16 or approximate offset conversion. */
export function sourceSlice(text: string, start: number, end: number): string { return Array.from(String(text ?? '')).slice(start, end).join(''); }
export function exactSourceSpan(text: string, ref: SourceRef): boolean {
  return Number.isInteger(ref.start) && Number.isInteger(ref.end) && ref.start! >= 0 && ref.end! >= ref.start!
    && ref.end! <= Array.from(text).length && typeof ref.quote === 'string' && sourceSlice(text, ref.start!, ref.end!) === ref.quote;
}
export function describe(value: unknown): string {
  if (value == null) return 'Not documented';
  if (typeof value !== 'object') return String(value);
  if (Array.isArray(value)) return value.map(describe).join('; ');
  const object = value as RawRecord;
  for (const key of ['answer', 'text', 'display_text', 'statement', 'description', 'message', 'reason', 'label', 'result', 'value']) {
    if (object[key] != null) return `${describe(object[key])}${object.unit ? ` ${object.unit}` : ''}`;
  }
  return Object.entries(object).filter(([key]) => !['source_refs', 'evidence', 'refs', 'citations', 'all_refs'].includes(key))
    .map(([key, item]) => `${key.replaceAll('_', ' ')}: ${describe(item)}`).join(' · ');
}
export const dataAdapter = new ClinicalDataAdapter();
