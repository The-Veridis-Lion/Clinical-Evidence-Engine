"""Human-readable output from the same sealed machine-readable packet."""


def render_readable_markdown(packet):
    """Readable, source-linked draft; the original audit export stays available."""
    from .presentation import draft_presentation
    view = draft_presentation(packet)
    counts = view['summary']
    lines = [f'# SOAP draft · {packet.case_id}', '',
             f'Patient: {packet.patient_id} · Encounter: {packet.source.encounter_time or "Not documented"} · Version: {packet.version}',
             'Supporting evidence draft. Extraction and demonstration do not require sign-off. A qualified healthcare professional must independently review original evidence before diagnosis, treatment, medication or other substantive patient-care decisions. Machine checks and human decisions are recorded separately.',
             f'{counts["specific_risks"]} assertions with specific risk flags; {counts["machine_unverified"]} not confirmed by automatic checks; {counts["human_reviewed"]} reviewed by a person.',
             'These counts can overlap. An unconfirmed machine check is not a finding that the assertion is false.',
             f'Extraction: {packet.extraction_status}. Complete clinical coverage and independent clinical accuracy are not established.',
             f'Source: {packet.source.document_id} · SHA256: `{packet.source.sha256}`',
             f'Packet hash: `{packet.content_hash}`', '']
    for section, title in [('S', 'Subjective'), ('O', 'Objective'), ('A', 'Assessment'), ('P', 'Plan')]:
        lines += [f'## {section} · {title}', '']
        for row in view['sections'][section]:
            fields = '; '.join(f'{f["label"]}: {f["value"]}' for f in row['fields'])
            lines += [f'- {row["display_text"]}',
                      f'  Retained fields: {fields}.',
                      f'  Claim: `{row["fact_id"]}` · Evidence: ' + ', '.join(f'`{e}`' for e in row['evidence_ids']),
                      f'  Automatic check: {row["machine_status"]}. Human review: {row["review_status"]}.']
            if row['section_note']:
                lines.append('  ' + row['section_note'])
            for note in row.get('presentation_notes', []):
                lines.append('  ' + note)
            if row.get('not_adopted_dimensions'):
                lines.append('  Not adopted into this draft: '+', '.join(
                    d['dimension'] for d in row['not_adopted_dimensions'])+'. Original proposals remain in the audit export.')
            if row['human_reviewed']:
                review = row['human_review']
                lines.append(f'  Human decision: {review["action"]} by {review["reviewer_id"]} at v{review["version"]}: {review["reason"]}. Automatic check unchanged.')
                lines.append('  Human review task completed.' if row['human_review_complete'] else '  Human decision saved; outstanding review questions remain.')
            if row['specific_risk']:
                lines.append('  **Specific risk remains — inspect the original source and recorded concerns.**')
            if row['review_targets']:
                lines.append('  Check dimensions: ' + ', '.join(row['review_targets']) + '.')
            for issue in row['issues']:
                if issue['severity'] == 'high' or not issue['code'].startswith('source_'):
                    lines.append(f'  Recorded concern ({issue["code"]}): {issue["question"]}')
            for conflict in row['conflicts']:
                lines.append(f'  Recorded conflict: {conflict["reason"]}')
        if not view['sections'][section]:
            lines.append('Not documented in the accepted extraction.')
        lines.append('')
    if view['relationship_proposals']:
        lines += ['## Relationship proposals', '',
                  'Retained extraction proposals. Endpoint and quotation checks do not establish clinical meaning.', '']
        for row in view['relationship_proposals']:
            def endpoint(side):
                e = row[side]
                return f'input index {e["input_index"]} · {e["original_concept"] or "unresolved concept"} · {e["fact_id"] or "unresolved identity"}'
            lines += [f'- `{row["relationship_id"]}`: {endpoint("from")} → {row["relation"]} → {endpoint("to")}',
                      f'  Status: {row["status"]}; structure: {row["structural_status"]}; adopted in sealed SOAP: {row["adopted_in_soap"]}.']
            if row['structural_concern']:
                lines.append('  ' + row['structural_concern'])
            for span in row['citations']:
                lines += [f'  Source characters [{span.get("start")}:{span.get("end")}] · exact source match: {span["source_match"]}',
                          *['> ' + line for line in str(span.get('quote', '')).splitlines()], '']
    lines += ['## Original evidence', '']
    for evidence in packet.evidence:
        lines += [f'### {evidence.evidence_id}',
                  f'{evidence.document_id} · {evidence.turn_id} · {evidence.speaker_label or "Clinical note"} · characters [{evidence.start}:{evidence.end}]',
                  '', *['> ' + line for line in evidence.quote.splitlines()], '']
    general = [i for i in packet.issues if not i.fact_ids]
    if general or packet.rejected_facts:
        lines += ['## Extraction issues', '']
        lines += [f'- {issue.code}: {issue.question}' for issue in general]
        lines += [f'- Rejected proposal {f["original_index"]}: {f["reason"]}' for f in packet.rejected_facts]
    lines += ['', 'The full audit Markdown and evidence JSON retain every machine check, relationship proposal, source span and immutable revision.']
    return '\n'.join(lines) + '\n'


def render_markdown(packet):
    packet.verify()
    lines = [f'# Clinical Evidence Copilot · {packet.case_id}',
             f'Patient: {packet.patient_id} · Version: {packet.version}',
             'Supporting evidence draft only. Qualified professional review of original evidence is required before substantive patient-care decisions. No clinical validation, regulatory approval or compliance certification is claimed.',
             f'Packet hash: `{packet.content_hash}`',
             f'Extraction: {packet.extraction_status} · Interpretation: not clinically validated',
             f'Source: {packet.source.document_id} · SHA256: `{packet.source.sha256}`',
             f'Encounter time (metadata): {packet.source.encounter_time or "Not documented"}',
             f'Review required: {len(packet.review_required_fact_ids)} / {len(packet.facts)} facts', '']
    if packet.extraction_metadata.get('soap_projection_version') == 'soap/v4':
        from .atomic import coverage_report
        coverage = coverage_report(packet)
        lines += ['DRAFT · REVIEW REQUIRED. Exact citations establish location; semantic source support and complete clinical coverage remain unverified.', '',
            'Confirmed clinical facts: none automatically certified. Review decisions remain separately recorded.', '',
            f'Atomic coverage: {coverage.get("independent_assertions",0)} independently supplied assertions; semantic completeness UNVERIFIED.', '']
    if packet.extraction_metadata.get('soap_projection_version') in {'soap/v5', 'soap/v6'}:
        from .atomic import coverage_report
        coverage = coverage_report(packet)
        rows = packet.extraction_metadata['evidence_verification']['assertions']
        supported = sum(r['result']['status'] == 'SUPPORTED_BY_SOURCE' for r in rows)
        eligible = sum(r['result']['risk_route'] == 'AUTO_ACCEPT_ELIGIBLE' for r in rows)
        lines += [f'Source-supported proposals: {supported}/{len(rows)}. Automatic processing eligible: {eligible}/{len(rows)}.',
                  'Source support describes documented evidence, not independent clinical expert validation.',
                  'Source-first coverage remains PARTIAL; unknown meanings and source model candidates stay reviewable.', '']
    for s, title in [('S', 'Subjective'), ('O', 'Objective'), ('A', 'Assessment'), ('P', 'Plan')]:
        lines += [f'## {s} · {title}', '']
        for a in packet.soap[s]:
            lines += [f'- {a.text} [{", ".join(a.fact_ids)}] · {a.review_status}' + (' · REVIEW REQUIRED' if a.requires_review else '')]
        if not packet.soap[s]:
            lines += ['Not documented in the accepted extraction.']
        lines += ['']
    lines += ['## Evidence', '']
    for f in packet.facts:
        lines += [f'### {f.fact_id}', '']
        for e in (e for e in packet.evidence if e.evidence_id in f.evidence_ids):
            lines += [f'`{e.evidence_id}` · {e.document_id} · {e.turn_id} · {e.speaker_label or "unlabeled"} · [{e.start}:{e.end}] · lines {e.line_start}–{e.line_end}',
                      '', *['> ' + line for line in e.quote.splitlines()], '']
    lines += ['## Questions and conflicts', '']
    lines += [f'- {i.code}: {i.question} [{", ".join(i.fact_ids)}]' for i in packet.issues] or ['No automatic discrepancy flags. This is not clinical certification.']
    lines += ['', '## Review trail', '']
    lines += [f'- v{r.applied_version} · {r.reviewer.reviewer_type}/{r.reviewer.reviewer_id} ({r.reviewer.version}) · {r.action} {r.fact_id}: {r.reason} · evidence={", ".join(r.evidence_ids)}' for r in packet.reviews] or ['No review recorded. Saving a draft does not require a signature.']
    events = packet.extraction_metadata.get('program_reprocessing_events', [])
    if events:
        lines += ['', '## Program reprocessing', '']
        lines += [f'- v{e["base_version"]} → v{e["applied_version"]} · {e["profile_version"]}: {e["reason"]} · {len(e["changes"])} changed fact projections; zero model calls; no human approval created.' for e in events]
    if packet.rejected_facts:
        lines += ['', '## Rejected proposals', ''] + [f'- Index {r["original_index"]}: {r["reason"]}' for r in packet.rejected_facts]
    atomic = packet.extraction_metadata.get('atomic_source_checklist')
    verified = packet.extraction_metadata.get('evidence_verification')
    typed = packet.extraction_metadata.get('clinical_semantics_v2', [])
    if typed:
        lines += ['', '## Typed attribute and event proposals', '',
                  'These retained extraction/correction proposals are not independently confirmed attributes. See dimension evidence and targeted review below.', '']
        for row in typed:
            values = row['semantics']
            shown = '; '.join(f'{key}={values[key]}' for key in
                ('frequency', 'event_time', 'duration', 'action_type', 'action_state', 'completion_scope', 'assertion_basis')
                if values.get(key) is not None)
            lines.append(f'- {row["fact_id"]}: {shown} · source SHA256 `{row["source_sha256"]}`')
    if verified:
        lines += ['', '## Source verification', '']
        for row in verified['assertions']:
            result = row['result']
            lines.append(f'- {row["fact_id"]}: {result["status"]} · {result["risk_route"]} · ' + '; '.join(result['reasons']))
            if row.get('adoption'):
                scope=row['adopted_claim'].get('completion_scope')
                lines.append(f'  Adopted completion_scope: {scope or "not asserted"}. Proposal and source-check result retained separately.')
                for dimension in row['adoption']['not_adopted_dimensions']:
                    lines.append(f'  Not adopted: {dimension["dimension"]}; proposed={dimension["proposed_value"]}; source check={dimension["source_check_status"]}. '+dimension['reason'])
            if row.get('primary_reference_proposal'):
                anchor = row['primary_reference_proposal']
                order_note=('Selected primary passage adopted first; original citation order retained in raw response and audit metadata.'
                    if packet.extraction_metadata.get('structured_extraction_contract',{}).get('primary_reference_application')=='model-selected-primary/1'
                    else 'Original citation order retained.')
                lines.append(f'  Extraction anchor: {anchor["primary_source_id"] or "none"} · {anchor["status"]}. {order_note}')
            for ref in row.get('semantic_support_refs', []):
                lines.append(f'  Source-verified support ({ref["support_scope"]}) [{ref["start"]}:{ref["end"]}]: {ref["quote"]}')
            if row.get('components'):
                components = row['components']
                lines.append(f'  Main assertion: {components["main_assertion"]["status"]}; event: {components["event"]["status"]}; targeted review: {", ".join(components["review_targets"]) or "none"}.')
        automatic = (atomic or {}).get('automatic_source_coverage', {})
        for candidate in automatic.get('verified_omission_candidates', []):
            lines.append(f'- Omission candidate {candidate["assertion"]["claim_id"]}: {candidate["assertion"]["concept"]} · {candidate["source_verification"]["status"]}. Not automatically adopted.')
        for candidate in automatic.get('unresolved_alignment_candidates', []):
            lines.append(f'- Existing assertion alignment review {candidate["assertion"]["claim_id"]}: {candidate["assertion"]["concept"]}. {candidate["reason"]}')
    if atomic:
        mention = atomic.get('mention_source_coverage')
        if mention:
            lines += ['', '## Independent source mention candidates', '',
                f'Existing detector: {mention["status"]}; semantic completeness UNVERIFIED; no automatic fact completion.', '']
            for candidate in mention['candidates']:
                span = candidate['mention']
                lines.append(f'- {candidate["classification"]} [{span["start"]}:{span["end"]}] {span["quote"]}; source support UNVERIFIED; original context retained.')
        lines += ['', '## Source-unit and independent atomic coverage', '']
        for unit in atomic['source_units']:
            lines.append(f'- {unit["unit_id"]} [{unit["start"]}:{unit["end"]}] · {unit["citation_status"]} · semantic coverage UNVERIFIED · atoms={", ".join(unit["independent_assertion_ids"])}')
        for atom in atomic['independent_source_assertions']:
            lines.append(f'- {atom["assertion_id"]}: {atom["text"]} · {atom["decision"]} · {atom["reviewer_type"]}/{atom["reviewer_id"]} · {atom["reason"]}')
        if atomic['speaker_annotations']:
            lines += ['', 'Raw source speaker labels (declared roles unverified):', '']
            lines += [f'- [{a["start"]}:{a["end"]}] {a["raw_label"]} · inferred_role={a["inferred_role"]} · boundary_discrepancy={a["boundary_discrepancy"]}' for a in atomic['speaker_annotations']]
    return '\n'.join(lines) + '\n'
