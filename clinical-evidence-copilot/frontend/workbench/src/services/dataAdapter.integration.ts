/** Read-only existing-source integration. Only deterministic query POSTs allowed. */
import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {ClinicalDataAdapter, exactSourceSpan, rows, sourceRefs} from './dataAdapter.ts';
import type {RawRecord} from '../types/clinical.ts';

const base = new URL(process.argv[2] || 'http://127.0.0.1:8871');
assert.ok(['127.0.0.1', 'localhost'].includes(base.hostname), 'Local integration only');
const calls: {path: string; method: string}[] = [];
const api = new ClinicalDataAdapter((async (path: string, options: RequestInit) => {
  const method = options.method || 'GET';
  assert.ok(method === 'GET' || (method === 'POST' && path.endsWith('/queries')), 'Only deterministic query writes allowed');
  if (method === 'POST') assert.equal('question' in JSON.parse(String(options.body)), false);
  calls.push({path, method});
  return fetch(new URL(path, base), options);
}) as typeof fetch);

const config = await api.initialize();
const initialCalls = await api.request('/api/calls');
const patients = await api.getPatients();
const patientId = 'SYN-WB-001'; // Original saved synthetic demonstration cohort.
assert.ok(rows(patients.patients).some(patient => patient.patient_id === patientId));
const workspace = await api.getWorkspace(patientId);
assert.equal(rows(workspace.documents).length, 4);
assert.equal(rows(workspace.encounters).length, 3);
const evidence = new Map<string, RawRecord>();
for (const document of rows(workspace.documents)) {
  const ref = {case_id: document.case_id, packet_version: document.packet_version};
  const original = await api.getEvidence(patientId, ref);
  assert.equal(original.packet.version, document.packet_version);
  assert.equal(original.packet.content_hash, document.content_hash);
  assert.equal(typeof original.packet.source.text, 'string');
  assert.ok(original.packet.source.text.length > 0);
  evidence.set(`${document.case_id}:${document.packet_version}`, original);
}
let checkedSpans = 0;
let multiSpanStatements = 0;
const soaps: RawRecord[] = [];
for (const encounter of rows(workspace.encounters)) {
  const soap = await api.getSoap(patientId, encounter.encounter_id);
  assert.equal(soap.scope, 'selected_encounter');
  soaps.push(soap);
  for (const section of Object.values(soap.sections)) {
    for (const statement of rows(section)) {
      const refs = sourceRefs(statement);
      assert.ok(refs.length > 0);
      if (refs.length > 1) multiSpanStatements++;
      for (const ref of refs) {
        const key = `${ref.case_id}:${ref.packet_version}`;
        if (!evidence.has(key)) evidence.set(key, await api.getEvidence(patientId, ref));
        const packet = evidence.get(key)!.packet;
        assert.equal(packet.source.document_id, ref.document_id);
        assert.equal(exactSourceSpan(packet.source.text, ref), true, `Exact code-point source mismatch: ${key}`);
        checkedSpans++;
      }
    }
  }
}
assert.ok(multiSpanStatements > 0);
const duration = await api.query(patientId, {family: 'documented_duration_sum', filters: {concept: 'physical therapy session'}});
assert.equal(duration.answer.documented_minutes, 85);
assert.deepEqual(duration.answer.minutes, {lower: 85, upper: null, value: null});
assert.equal(duration.answer.complete, false);
assert.equal(rows(duration.missing_data).filter(row => row.reason === 'missing_or_nonexact_documented_duration').length, 1);
assert.equal(duration.model_calls, 0);
const cough = await api.query(patientId, {family: 'symptom_timeline', filters: {concept: 'cough'}});
assert.ok(rows(cough.answer.events).some(row => row.clinical_status === 'resolved'));
assert.equal(cough.model_calls, 0);
const requests = await api.getCareflowRequests(patientId);
assert.equal(rows(requests.requests).length, 3);
const careflow: RawRecord[] = [];
for (const request of rows(requests.requests)) careflow.push(await api.getCareflowRequest(patientId, request.case_id));
assert.deepEqual(careflow.map(result => result.packet.readiness).sort(), ['DOCUMENTATION_READY', 'DOCUMENTATION_READY', 'NOT_SUPPORTED'].sort());
const after = await api.getWorkspace(patientId);
assert.equal(after.evidence_version, workspace.evidence_version);
assert.deepEqual(rows(after.documents).map(document => [document.case_id, document.packet_version, document.content_hash]),
  rows(workspace.documents).map(document => [document.case_id, document.packet_version, document.content_hash]));
const finalCalls = await api.request('/api/calls');
assert.equal(finalCalls.dispatch_attempts, initialCalls.dispatch_attempts);
const output = {
  evidence_kind: 'Actual localhost adapter integration over saved Luna responses on authored synthetic sources',
  base_url: base.origin, runtime_model: config.runtime_model, patient_id: patientId,
  document_count: 4, encounter_count: 3, checked_codepoint_spans: checkedSpans,
  multi_span_statements: multiSpanStatements, new_extraction_dispatches: 0,
  clinical_versions_unchanged: true, allowed_requests: calls,
  source_inventory: [...evidence.values()].map(result => ({case_id: result.packet.case_id,
    version: result.packet.version, content_hash: result.packet.content_hash, source_sha256: result.packet.source.sha256})),
  duration, cough, careflow: careflow.map(result => ({case_id: result.packet.case_id, revision: result.packet.revision,
    readiness: result.packet.readiness, shared_binding: result.shared_binding})),
};
if (process.argv[3]) await writeFile(process.argv[3], JSON.stringify(output, null, 2));
console.log(JSON.stringify({pass: true, documents: 4, encounters: 3, checked_spans: checkedSpans,
  multi_span_statements: multiSpanStatements, duration_minutes: 85, missing_sessions: 1,
  careflow_states: careflow.map(result => result.packet.readiness), new_model_calls: 0}));
