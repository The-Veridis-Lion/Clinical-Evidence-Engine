"""Scoped source semantics v1; no gold, source-specific identifiers or arithmetic."""
from copy import deepcopy
from .domain import ServiceSource

VERSION = "semantic-contract-1"
RULES = """
Scoped source contract v1:
- Service data uses source {content_kind, transmission_status, original_signed,
  current_signed, source_disposition}. content_kind classifies this specific record's
  CONTENT. transmission_status describes this record/attachment, not the whole packet.
  original_signed describes a copied original's signature; current_signed describes
  a signature attached to THIS current record entry. Missing signature is null; an
  explicit unsigned entry is false. Final export/register status alone is not signing.
  Preserve the literal source_disposition when stated. Code derives evidence_kind
  and signed; do not supply those redundant fields in service data.
- An original signed attendance record resent without a new signature remains
  original_signed=true, current_signed=false, transmission_status=retransmitted.
  Keep the retransmits relationship. A mixed packet can also contain NEW original
  contact claims: do not mark those retransmitted. Receipt is not service date.
- A table and an attestation belonging to the SAME entry are complementary context,
  not automatically two source records. Use one compatible service claim with the
  applicable content kind and scheduled/actual fields. Separate genuinely distinct
  records, conflicting source statements, drafts and billing. An incidental arranged
  future contact without its own booking/contact record is a planned observation.
- Administrative Completed asserts the status of the described appointment; preserve
  that asserted presence/delivery without claiming actual clocks or signed clinical
  authority. Resolve its SCOPE from the linked row/detail: a completed partner-only
  contact asserts partner attendance, not patient presence or patient treatment.
  Do not invent a conflicting positive patient claim merely from Completed where
  the same entry explicitly explains patient absence. Preserve real source conflicts.
  Cancellation/no-show asserts no attendance at that scheduled slot; an independent
  callback/contact or later patient-present segment has its own scope.
- Literal ID roles may BOTH apply to one token if header/table and prose say so.
  Never invent Encounter merely because Appointment is known, or vice versa.
- Assessment source_role=result is an actual documented form/result. Use
  historical_mention for a referenced old score; keep it, with reference_date for
  the date expressly attributed to the mention. 'Score recorded on [date]' does NOT
  establish questionnaire completion: assessment_date=null unless completion is
  established. An attached original reviewed by a clinician is not copied merely
  because reviewed. A reproduced old score summary/mention is copied=true.
  Do not bind historical mentions to forms by equal score or borrowed current form ID.
- context_span_ids can cite multiple exact source lines for header identity, literal
  ID roles, signature, transmission, presence/delivery or time roles. Keep span_id
  as the main statement evidence. Cite applicable sections; another encounter's
  signature or assertion is not support. Do not assume one line proves every field.
- statement remains readable, source-faithful language including negation. polarity
  categorizes the clinical assertion, not a second negation of the whole sentence.
  'Has not established a routine' can be absent; do not invert it again. Reporter is
  the explicitly attributed speaker/observer; author/signature is not automatically
  every quote's reporter. Ongoing recent functioning may be current at the report;
  only an explicitly prior/resolved event is historical. Unknown stays not specified.
"""


def semantic_prompt(prompt):
    prompt=prompt.replace("A copy keeps\nthe original facts with retransmission evidence_kind and a retransmits relationship.",
                          "A copy preserves original facts and a scoped retransmits relationship.")
    prompt=prompt.replace("For each encounter and evidence kind, keep compatible facts together:",
                          "For each source record and encounter, keep compatible facts together:")
    prompt=prompt.replace("patient_present=false only when absence is stated, not merely lack of a service.",
                          "absence applies to the cancelled slot only, not to independent contacts.")
    prompt=prompt.replace("with evidence_kind=draft, signed=false", "as draft source content without current signing")
    prompt=prompt.replace("Use one exact original line for evidence; inherited header context can support other\nfields.",
                          "Use exact original lines for evidence and additional applicable context spans.")
    prompt=prompt.replace("keep compatible facts together: schedule,", "keep compatible facts together: schedule,")
    return prompt+"\n"+RULES


def semantic_examples(examples):
    from .luna_candidates import source_lines
    values=deepcopy(examples)
    for example in values:
        lines=source_lines(example['text'])
        headers=[k for k,(text,_,__) in lines.items() if 'MRN' in text or 'Document ID' in text]
        for row in example['extractions']:
            row['context_span_ids']=headers[:16]
            data=row['data']
            if row['kind']=='service':
                kind=data.pop('evidence_kind');signed=data.pop('signed')
                retransmitted=kind=='retransmission'
                data['source']=dict(content_kind='attendance' if retransmitted else kind,
                    transmission_status='retransmitted' if retransmitted else 'original',
                    original_signed=signed if retransmitted else None,
                    current_signed=False if retransmitted else signed,source_disposition=None)
            elif row['kind']=='assessment':
                data['source_role']='result';data['reference_date']=None
    return values


def project_payload(kind, payload):
    data=deepcopy(payload)
    if kind=='service':
        source=ServiceSource.model_validate(data['source'])
        data['evidence_kind']='retransmission' if source.transmission_status=='retransmitted' else source.content_kind
        data['signed']=source.original_signed if source.transmission_status=='retransmitted' else source.current_signed
        data['source']=source.model_dump()
    return data
