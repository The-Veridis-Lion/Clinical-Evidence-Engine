/** Transport/mapping contracts only; fake HTTP responses are not clinical data. */
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import {
  ClinicalDataAdapter, WorkbenchRequestError, sourceRefs, sourceSlice,
  exactSourceSpan, rows, capabilitiesList, describe,
} from './dataAdapter.ts';
import type { RawRecord } from '../types/clinical.ts';

function harness(responses: unknown[], live = false) {
  const calls: {path: string; options: RequestInit}[] = [];
  const api = new ClinicalDataAdapter((async (path: unknown, options: RequestInit) => {
    calls.push({path: String(path), options});
    const next = responses.shift();
    if (next instanceof Error) throw next;
    if (next instanceof Response) return next;
    return new Response(JSON.stringify(next), {status: 200, headers: {'Content-Type': 'application/json'}});
  }) as typeof fetch);
  api.config = {csrf_token: 'fixture-token', live_enabled: live};
  return {api, calls};
}

test('same-origin config and CSRF protect real writes without fallback or retry', async () => {
  const {api, calls} = harness([{csrf_token: 'saved-token', live_enabled: false}, {patient_id: 'p'}]);
  api.config = {};
  await assert.rejects(api.createPatient({patient_id: 'p'}), /write token/);
  assert.equal(calls.length, 0);
  await api.initialize();
  assert.deepEqual(await api.createPatient({patient_id: 'p'}), {patient_id: 'p'});
  assert.equal(calls[0].path, '/api/config');
  assert.equal(calls[1].path, '/ui/patients');
  assert.equal((calls[1].options.headers as RawRecord)['X-Copilot-Token'], 'saved-token');
  assert.equal(calls[1].options.credentials, 'same-origin');
  assert.equal(calls[1].options.cache, 'no-store');
  await assert.rejects(api.request('https://external.invalid/api'), /same-origin/);
  assert.equal(calls.length, 2);
});

test('revision conflicts and transport failures never become saved-success objects', async () => {
  const conflict = {error: 'Fact changed since this editor was opened', current_version: 4};
  const {api, calls} = harness([new Response(JSON.stringify(conflict), {status: 409}), new Error('network failed')]);
  const correction = {base_version: 2, replacement: {concept: 'reported symptom'}, reason: 'source-backed edit'};
  await assert.rejects(api.correction('patient', 'case', 'fact', correction), error => {
    assert.ok(error instanceof WorkbenchRequestError);
    assert.equal(error.status, 409); assert.deepEqual(error.payload, conflict); return true;
  });
  assert.deepEqual(JSON.parse(String(calls[0].options.body)), correction);
  await assert.rejects(api.getWorkspace('patient'), /has not been saved/);
  assert.equal(calls.length, 2);
  assert.equal('saveSOAP' in api, false);
});

test('SOAP and evidence retain every raw source, exact versions, history and full text', async () => {
  const refs = [{case_id: 'one', packet_version: 2, document_id: 'd1', start: 2, end: 5, quote: 'abc'},
    {case_id: 'two', packet_version: 1, document_id: 'd2', start: 0, end: 3, quote: 'def'}];
  const soap = {sections: {S: [{display_text: 'Saved statement', source_refs: refs}]}, saved_version: [{case_id: 'one', version: 2}], missing_documents: [{document_id: 'queued'}]};
  const evidence = {packet: {source: {text: '😀\nabc\ncomplete original source'}, version: 2, content_hash: 'actual-hash'}, history: [{version: 1}, {version: 2}], presentation: {sections: {}}};
  const {api, calls} = harness([soap, evidence, [{version: 1}, {version: 2}], {version: 1}]);
  assert.deepEqual(await api.getSoap('p/a', 'v b'), soap);
  assert.deepEqual(await api.getEvidence('p/a', {case_id: 'c/x', packet_version: 2}), evidence);
  assert.deepEqual(await api.getHistory('c/x'), [{version: 1}, {version: 2}]);
  assert.deepEqual(await api.getPacket('c/x', 1), {version: 1});
  assert.equal(calls[0].path, '/ui/patients/p%2Fa/encounters/v%20b/soap');
  assert.equal(calls[1].path, '/ui/patients/p%2Fa/evidence/c%2Fx?version=2');
  assert.equal(calls[2].path, '/api/cases/c%2Fx/history');
  assert.equal(calls[3].path, '/api/cases/c%2Fx?version=1');
});

test('all supporting sources and Unicode code-point positions survive without guessed spans', () => {
  const text = '😀\nabc\nanswer';
  const first = {case_id: 'one', start: 2, end: 5, quote: 'abc'};
  const second = {case_id: 'two', start: 0, end: 6, quote: 'answer'};
  assert.equal(sourceSlice(text, 2, 5), 'abc');
  assert.equal(exactSourceSpan(text, first), true);
  assert.equal(exactSourceSpan(text, {...first, start: 3}), false);
  assert.equal(exactSourceSpan(text, {...first, end: 500}), false);
  assert.equal(exactSourceSpan(text, {start: null, end: null, quote: null}), false);
  assert.deepEqual(sourceRefs({...first, all_refs: [first, second]}), [first, second]);
  assert.deepEqual(sourceRefs({source_refs: [first, second]}), [first, second]);
  assert.deepEqual(sourceRefs({case_id: 'one', fact_id: 'fact', document_id: 'd', source_refs: [first, second]}), [first, second]);
});

test('duration uncertainty, exclusions, missing values and symptom assertions stay server-authored', async () => {
  const result = {answer: {documented_minutes: 85, minutes: {lower: 85, upper: null, value: null}, complete: false},
    calculation_steps: [{inputs: {duration_identity_assessment: [{event_date: '2026-09-03', event_time: 'September 3, 2026'}]}}],
    excluded_records: [{reason: 'duplicate_same_source_assertion'}], missing_data: [{reason: 'missing_or_nonexact_documented_duration'}]};
  const timeline = {answer: {events: [{concept: 'cough', clinical_status: 'resolved', time_basis: 'encounter_record'}], clinical_trend: 'NOT_INFERRED'}};
  const {api, calls} = harness([result, timeline]);
  assert.deepEqual(await api.query('p', {family: 'documented_duration_sum', filters: {concept: 'therapy'}}), result);
  assert.deepEqual(await api.query('p', {family: 'symptom_timeline', filters: {concept: 'cough'}}), timeline);
  assert.equal(calls.length, 2);
  assert.deepEqual(rows(null), []);
  assert.equal(describe(0), '0');
  assert.equal(describe({value: 0, unit: 'minutes'}), '0 minutes');
  assert.deepEqual(capabilitiesList({families: [{family: 'visit_count'}]}), [{family: 'visit_count'}]);
});

test('all CareFlow criterion states and actual proofs remain intact through real action routes', async () => {
  const states = ['SUPPORTED', 'NOT_SUPPORTED', 'INSUFFICIENT_EVIDENCE', 'CONFLICTED', 'NOT_APPLICABLE'];
  const packet = {packet: {case_id: 'cf', revision: 3, readiness: 'NEEDS_EVIDENCE', checks: states.map(status => ({status, source_refs: [{quote: 'Original labelled material'}], gaps: ['Original missing field']}))}, shared_binding: {stale: true}};
  const {api, calls} = harness([packet, {packet: {revision: 4}}, {packet: {revision: 5}}, {packet: {revision: 6}}]);
  assert.deepEqual(await api.getCareflowRequest('p', 'cf'), packet);
  const body = {expected_revision: 3, document: {text: 'Patient ID: p\nProvider ID: explicit-id'}, intake: {basis_revision: 3, basis_packet_sha256: 'saved-hash'}};
  await api.addCareflowDocument('p', 'cf', body);
  await api.recalculateCareflow('p', 'cf', {expected_revision: 4, basis_packet_sha256: 'next-hash'});
  await api.syncCareflow('p', 'cf', {reason: 'Explicit refresh'});
  assert.deepEqual(JSON.parse(String(calls[1].options.body)), body);
  assert.equal(calls[1].path, '/ui/patients/p/careflow/requests/cf/documents');
  assert.equal(calls[2].path, '/ui/patients/p/careflow/requests/cf/recalculate');
  assert.equal(calls[3].path, '/ui/patients/p/careflow/requests/cf/sync-shared');
});

test('per-file statuses and actual correction revisions are never optimistic fake saves', async () => {
  const files = [{document_id: 'a', text: 'Original source', input_kind: 'note', encounter_id: 'v', encounter_time: '2026-09-03'}];
  const jobs = {files: [{document_id: 'a', status: 'queued'}, {document_id: 'b', status: 'uncertain', error: 'retained timeout'}], automatic_retries: 0};
  const saved = {packet: {version: 7, parent_hash: 'prior-hash', content_hash: 'new-hash'}, careflow_sync: [{case_id: 'cf', status: 'stale'}], model_calls: 0};
  const {api, calls} = harness([jobs, saved]);
  assert.deepEqual(await api.files('p', files), jobs);
  assert.deepEqual(JSON.parse(String(calls[0].options.body)), {files});
  assert.deepEqual(await api.correction('p', 'case', 'fact', {base_version: 6, action: 'correct'}), saved);
  assert.equal(calls.length, 2);
});

test('optional Luna actions require live capability and explicit interpretation opt-in', async () => {
  const {api, calls} = harness([{status: 'needs_clarification'}, {proposal: {sections: {S: []}}, model_calls: 1}]);
  assert.throws(() => api.polish('p', 'v', 'hash'), /offline/);
  assert.throws(() => api.interpretQuestion('p', 'How many?', true), /offline/);
  api.config.live_enabled = true;
  assert.throws(() => api.interpretQuestion('p', 'How many?', false), /opt-in/);
  assert.throws(() => api.query('p', {question: 'How many?'}), /opt-in/);
  assert.throws(() => api.query('p', {question: 'How many?', allow_model: true, model: 'developer-model'}), /gpt-6-luna only/);
  assert.equal(calls.length, 0);
  await api.interpretQuestion('p', 'How many?', true);
  await api.polish('p', 'v', 'evidence-version');
  for (const call of calls) {
    const body = JSON.parse(String(call.options.body));
    assert.equal(body.allow_model, true); assert.equal(body.model, 'gpt-6-luna'); assert.ok(body.request_id);
  }
  assert.equal(JSON.parse(String(calls[1].options.body)).evidence_version, 'evidence-version');
});

test('key point organization sends selected IDs while legacy request stays unchanged', async () => {
  const {api,calls}=harness([{},{}],true);
  await api.polish('p','v','version');
  await api.polish('p','v','version',['S:one','O:two']);
  const oldBody=JSON.parse(String(calls[0].options.body));
  const keyPointBody=JSON.parse(String(calls[1].options.body));
  assert.equal('statement_ids' in oldBody,false);
  assert.deepEqual(keyPointBody.statement_ids,['S:one','O:two']);
  assert.equal(keyPointBody.allow_model,true);
  assert.equal(keyPointBody.model,'gpt-6-luna');
});

test('original saved Luna demonstration response is passed through unchanged, not a mock fallback', async () => {
  const path = new URL('../../../../../docs/patient-workbench/live/soap-visit-2026-09-08-response.json', import.meta.url);
  const original = JSON.parse(await readFile(path, 'utf8'));
  const {api} = harness([original]);
  assert.deepEqual(await api.getSoap('SYN-WB-001', 'visit-2026-09-08'), original);
  const refs = Object.values(original.sections).flatMap((section: any) => section.flatMap((row: RawRecord) => row.source_refs));
  assert.ok(refs.length > 1);
  assert.ok(new Set(refs.map((ref: any) => ref.document_id)).size > 1);
  const source = await readFile(new URL('./dataAdapter.ts', import.meta.url), 'utf8');
  assert.equal(source.includes('mockClinicalData'), false);
});
