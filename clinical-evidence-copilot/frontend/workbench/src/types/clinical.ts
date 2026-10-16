/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

/** Raw responses keep server fields and all uncertainty/version metadata. */
export type RawRecord = Record<string, any>;
export interface WorkbenchConfig extends RawRecord {
  csrf_token?: string;
  live_enabled?: boolean;
  careflow_url?: string | null;
  runtime_model?: string;
}
export interface SourceRef extends RawRecord {
  case_id?: string;
  packet_version?: number;
  document_id?: string;
  fact_id?: string | null;
  evidence_id?: string;
  start?: number | null;
  end?: number | null;
  quote?: string | null;
  reference_kind?: string;
  all_refs?: SourceRef[];
}
export interface UploadFile extends RawRecord {
  document_id: string;
  filename?: string;
  text: string;
  input_kind: 'note' | 'dialogue';
  source_patient_id?: string;
  encounter_id?: string | null;
  encounter_time?: string | null;
}
export type CareFlowCriterionState = 'SUPPORTED' | 'NOT_SUPPORTED'
  | 'INSUFFICIENT_EVIDENCE' | 'CONFLICTED' | 'NOT_APPLICABLE';
export type CareFlowReadiness = 'DOCUMENTATION_READY' | 'NOT_SUPPORTED' | 'NEEDS_EVIDENCE' | 'CONFLICTED';

// Original design-only interfaces remain import-compatible. Runtime components
// consume actual server records and do not fill these fields with mock values.
export interface Patient {
  id: string;
  name: string;
  dob: string;
  gender: 'Female' | 'Male' | 'Other';
  mrn: string;
  primaryCondition: string;
}

export interface ClinicalDocument {
  id: string;
  title: string;
  docType: 'transcript' | 'consult_note' | 'radiology_report' | 'physical_therapy' | 'order_form';
  visitDate: string;
  visitId?: string;
  author: string;
  facility: string;
  rawText: string;
  processedStatus: 'READY' | 'PROCESSING' | 'ERROR';
  lunaProcessedAt?: string;
}

export interface ProvenanceSource {
  documentId: string;
  documentTitle: string;
  date: string;
  startOffset: number;
  endOffset: number;
  speaker?: 'Physician' | 'Patient' | 'Physical Therapist' | 'Radiologist';
  exactQuote: string;
  dialogueContext?: string; // Doctor inquiry + patient answer paired context
}

export interface ClinicalStatement {
  id: string;
  section: 'subjective' | 'objective' | 'assessment' | 'plan';
  text: string;
  sources: ProvenanceSource[];
  riskFlag?: {
    type: 'contradiction' | 'temporal_ambiguity' | 'unverified_numerical';
    explanation: string;
    conflictingSources?: ProvenanceSource[];
  };
}

export interface SOAPNote {
  visitId: string;
  visitDate: string;
  encounterType: string;
  attendingPhysician: string;
  subjective: ClinicalStatement[];
  objective: ClinicalStatement[];
  assessment: ClinicalStatement[];
  plan: ClinicalStatement[];
  lastSavedAt: string;
  version: number;
  isModified?: boolean;
}

export interface MetricCalculationTrace {
  metricKey: string;
  title: string;
  primaryAnswer: string;
  secondaryLabel?: string;
  howCalculated: {
    formula: string;
    eventsUsed: {
      date: string;
      docId: string;
      docTitle: string;
      finding: string;
      offset: number;
    }[];
    timeWindow: string;
    deduplicationRule: string;
    exclusions: string[];
    uncertaintyNotice?: string;
  };
}

export interface SymptomMatrixRow {
  symptom: string;
  visit1Status: string;
  visit2Status: string;
  visit3Status: string;
  trajectory: 'Worsening' | 'Stable' | 'Refractory' | 'New Finding';
  provenanceDocIds: string[];
}

export interface CareFlowCriterion {
  id: string;
  category: 'formal_order' | 'clinical_prerequisite' | 'diagnostic_verification';
  title: string;
  ruleCode: string;
  requiredValue: string;
  extractedValue: string;
  status: 'SATISFIED' | 'DEFICIENT' | 'ACTION_REQUIRED';
  sourceType: 'formal_document' | 'clinical_narrative';
  provenance?: ProvenanceSource;
  notes: string;
}

export interface CareFlowPacket {
  packetId: string;
  requestType: string;
  targetProcedure: string;
  payerName: string;
  status: 'DOCUMENTATION_READY' | 'CRITERIA_PENDING' | 'ACTION_NEEDED';
  disclaimer: string;
  lastEvaluatedAt: string;
  criteria: CareFlowCriterion[];
  auditLog: {
    timestamp: string;
    action: string;
    actor: string;
    details: string;
  }[];
}
