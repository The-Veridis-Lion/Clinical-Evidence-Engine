"""Uncertainty contract v1, shared by generation and source-state inspection."""
from copy import deepcopy

VERSION = 'uncertainty-contract-1'
RULES = '''
Uncertainty contract v1:
Extract every fact supported by the source. Use an unknown or null value only when
the required information cannot be established from the available evidence.
Do not guess, but do not abstain when the evidence is sufficient.
Required means include the key, not invent a non-null value. For nullable fields
use JSON null, never empty strings, "unknown", zero, or false as a missing value.
Reporter/experiencer alone use the canonical role "not specified" when unknown.
Arrays contain supported items only; [] asserts no extracted items, not zero care.
- signed: true only for an applicable explicit signature; false only if explicitly
  unsigned/not signed; otherwise null. No signature shown is not proof of unsigned.
- patient_present: actual presence=true, explicit absence=false, otherwise null.
  Administrative Completed alone does not establish presence or delivery. Keep the
  literal disposition in reason; do not discard the scheduling claim.
- delivered: actual patient service clearly described=true, explicit nondelivery=false,
  otherwise null. Arrival alone is not proof of delivery; missing clocks is not absence.
- service_date: actual service date only. Document/signature/receipt dates cannot fill it.
- copied: explicitly copied/imported/retransmitted=true, explicitly original=false,
  otherwise null. Review alone does not establish either copying or originality.
- Every numeric field, date, source identity/role, category, relationship type/field,
  and temporal label may be null if not established. Keep a partial quantitative plan
  with its supported requirements and null missing components; never substitute zero.
  A qualitative recommendation remains an observation. service_types=[] when unknown.
  week_basis is monday_sunday only if that weekly basis is established; else null.
- Retain incomplete literal clock intervals with null missing endpoints. They do not
  supply a zero duration; code computes only complete intervals and propagates gaps.
- statement must faithfully describe the supported assertion, including negation and
  unresolved alternatives. Do not invent a neutral proposition by deleting negative words.
  polarity=uncertain means ambiguous assertion; null means no polarity established.
- uncertainty_notes is a short list of {field,state,explanation} for ambiguous or
  not-applicable nulls, and important undocumented gaps. state is not_documented,
  ambiguous, or not_applicable. Other nulls default to not_documented. Notes reference
  fields of this claim and do not overwrite supported values. Supported incompatible
  sources are separate claims, retained for code's conflicting state, never collapsed
  into one null. Known fields require no note.
- Preserve unknown patient identity without inventing a name/MRN; code isolates an
  unlinked document and never merges two unknown patients. Pure administrative text
  with no service facts has zero service claims; do not manufacture an unknown service.
'''


def field_state(claim, field):
    value = getattr(claim, field)
    note = next((n for n in claim.uncertainty_notes if n.field == field), None)
    return note.state if note else 'not_documented' if value is None or value == [] else 'known'


def uncertainty_prompt(prompt):
    prompt = prompt.replace('Plan: numerical weekly days AND patient-present minutes plus effective date are\nrequired.',
        'Plan: retain explicit quantitative weekly requirements, even if a date or one threshold is missing.')
    prompt = prompt.replace('Unsigned scheduling records\n  remain signed=false.',
        'Explicitly unsigned scheduling records remain signed=false; missing signature is null.')
    prompt = prompt.replace('A completed/attended appointment status asserts presence and delivery in that\n  SOURCE\'s schedule claim; it still supplies no actual clock attestation. Preserve\n  its asserted status, signed=false, evidence_kind=schedule.',
        'A Completed status is administrative schedule evidence; preserve it in reason. It alone establishes neither patient presence nor actual delivery, and supplies no signature or actual clock attestation.')
    prompt = prompt.replace('A clinician\'s observation or\npassive \'no ideation was reported\' statement can use the source clinician as\nreporter;',
        'A clearly attributed clinician observation uses that clinician; a passive statement without attribution uses not specified as reporter;')
    return prompt + '\n' + RULES


def nullable_prompt(prompt):
    # Keep the existing clinical taxonomy, scope and observation instructions.
    # Replace only statements that contradict the nullable source contract.
    prompt = prompt.replace('Plan: numerical weekly days AND patient-present minutes plus effective date are\nrequired.',
        'Plan: keep supported quantitative weekly requirements; missing dates or thresholds are null.')
    prompt = prompt.replace('Unsigned scheduling records\n  remain signed=false.',
        'Explicitly unsigned schedules have signed=false; missing signature information is null.')
    prompt = prompt.replace('A completed/attended appointment status asserts presence and delivery in that\n  SOURCE\'s schedule claim; it still supplies no actual clock attestation. Preserve\n  its asserted status, signed=false, evidence_kind=schedule.',
        'A Completed appointment status is schedule evidence. Preserve the literal status in reason; actual presence/delivery and signature are null unless separately established.')
    return prompt + '''
Nullable source contract:
Extract every fact supported by the source. Use an unknown or null value only when
the required information cannot be established from the available evidence.
Do not guess, but do not abstain when the evidence is sufficient.
Required keys may have JSON null. Missing is never false, zero, or an empty string.
signed is true for an applicable explicit signature, false for explicitly unsigned,
otherwise null. copied is true for explicitly reproduced/imported results, false for
explicit originals, otherwise null. Unknown reporter/experiencer is not specified;
the signer alone is not proof of each statement's reporter. Do not borrow date roles.
Described patient participation in a clinical intervention establishes delivery;
do not demand the literal phrase 'treatment delivered' or abstain from adequate context.
Keep supported partial plans and clock endpoints with null missing components.
uncertainty_notes may explain nulls, partial interval endpoints (e.g. actual_intervals[0].end),
ambiguity or not_applicable. Other nulls mean not_documented; known values need no notes.
Retain incompatible supported claims for code's conflict handling. Empty arrays retain
no unsupported items and are not a finding of zero care. No target facts means no claims.
'''


def uncertainty_examples(examples):
    values = deepcopy(examples)
    # This explicit unsigned desk-export example distinguishes administrative
    # Completed from patient attendance. The partner-only row remains negative.
    for ex in values:
        for row in ex['extractions']:
            if row['kind'] != 'patient':
                row['data'].setdefault('uncertainty_notes', [])
            if row['kind'] == 'service' and row['data'].get('evidence_kind') == 'schedule' and row['data'].get('patient_present') is True:
                row['data'].update(patient_present=None, delivered=None, reason='Source disposition Completed; no actual attendance or delivery assertion.')
    text = ('Patient: Test Person | MRN: EX-UP1 | Document ID: EX-UD1\n'
            'Clinical entry Encounter EX-UE1: individual psychotherapy booking. Patient arrived 10:00; departure and actual treatment delivery not documented. Service date not supplied. Signature not shown.\n'
            'PHQ-9 form EX-UF1: score blank; completion date and original/copy status not supplied.\n')
    from .luna_candidates import payload_schema
    def complete(kind, quote, data):
        properties = payload_schema(kind, uncertainty=True)['properties']
        row = {k: [] if v.get('type') == 'array' else None for k,v in properties.items()}
        row.update(data)
        return dict(kind=kind, quote=quote, data=row)
    lines = text.splitlines()
    values.append(dict(text=text, extractions=[
        complete('patient', lines[0], dict(patient_id='EX-UP1', name='Test Person', declared_id='EX-UD1')),
        complete('service', lines[1], dict(statement='Patient arrived; departure and treatment delivery undocumented.', encounter_ref='EX-UE1',
            service_type='individual', evidence_kind='clinical', patient_present=True, actual_intervals=[dict(start='10:00',end=None)],
            uncertainty_notes=[dict(field='delivered',state='not_documented',explanation='Only arrival is stated.')])),
        complete('assessment', lines[2], dict(statement='Blank PHQ-9 form.', instrument='PHQ-9', form_ref='EX-UF1', reporter='not specified', experiencer='not specified'))]))
    return values
