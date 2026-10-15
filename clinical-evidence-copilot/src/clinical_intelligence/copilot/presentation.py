"""Read-only draft display; reviewer decisions never become machine verification."""


VERSION = 'copilot-draft-presentation/1'


def draft_presentation(packet):
    """Project retained fields for readers without changing the sealed packet."""
    packet.verify()
    from .service import consumed_claim
    records = {r['fact_id']: r for r in
               packet.extraction_metadata.get('evidence_verification', {}).get('assertions', [])}
    sections = {key: [] for key in 'SOAP'}
    section_by_fact = {identity: key for key, rows in packet.soap.items()
                       for row in rows for identity in row.fact_ids}
    facts = []
    for item in packet.facts:
        fact = item.assertion
        record = records.get(item.fact_id, {})
        result = record.get('result', {})
        machine = result.get('status', 'UNVERIFIED')
        issues = [i.model_dump(mode='json') for i in packet.issues if item.fact_id in i.fact_ids]
        conflicts = [c.model_dump(mode='json') for c in packet.conflicts if item.fact_id in c.fact_ids]
        risks = [i for i in issues if i['severity'] == 'high']
        latest = next((r for r in reversed(packet.reviews) if r.fact_id == item.fact_id), None)
        # A historical human review of another assertion cannot label this one.
        human = bool(latest and latest.reviewer.reviewer_type == 'human'
                     and latest.after == fact.model_dump()
                     and latest.action in {'accept', 'correct'}
                     and item.review_status in {'accepted', 'corrected'})
        fields = [('Status', fact.polarity), ('Time', fact.temporality),
                  ('Subject', fact.experiencer), ('Reported by', fact.assertion_basis or 'unknown')]
        if fact.clinical_status:
            fields.append(('Documented qualifier', fact.clinical_status))
        # The proposed claim already binds the typed sidecar to the current
        # assertion. A stale sidecar is not independently read from metadata.
        proposal = consumed_claim(record)
        attributes = proposal.get('attributes')
        if attributes is None:
            attributes = fact.attributes.model_dump() if fact.attributes else {}
        for key in ('severity', 'frequency', 'duration', 'value', 'unit'):
            if attributes.get(key) is not None:
                fields.append((key.replace('_', ' ').capitalize(), str(attributes[key])))
        for key in ('event_time', 'action_state', 'completion_scope'):
            if proposal.get(key) not in (None, 'unknown'):
                fields.append((key.replace('_', ' ').capitalize() + ' (proposal)', str(proposal[key])))
        risk = bool(risks or conflicts or machine in {'CONTRADICTED', 'CONFLICTED'}
                    or item.review_status in {'questioned', 'escalated'})
        sealed_section = section_by_fact.get(item.fact_id, 'S')
        stored_action = next((r.get('action_state') for r in
            packet.extraction_metadata.get('action_state_checklist', {}).get('assertions', [])
            if r.get('fact_id') == item.fact_id), None)
        proposed_plan = (fact.temporality == 'planned' and proposal.get('action_state') == 'planned'
                         and fact.category in {'medication', 'procedure', 'treatment'}
                         and fact.experiencer == 'patient' and fact.polarity == 'present'
                         and fact.assertion_basis != 'discussion' and not risk
                         and item.action_status in {'planned', 'unknown'}
                         and stored_action not in {'discussed', 'not_completed', 'ongoing', 'completed'}
                         and not record.get('components', {}).get('event', {}).get('modality'))
        display_section = 'P' if proposed_plan else sealed_section
        row = {
            'fact_id': item.fact_id, 'concept': fact.concept or 'Unnormalized source assertion',
            'fields': [{'label': label, 'value': value} for label, value in fields],
            'evidence_ids': list(item.evidence_ids),
            'machine_status': machine, 'machine_route': result.get('risk_route', 'REVIEW_REQUIRED'),
            'machine_reasons': result.get('reasons', []),
            'review_targets': record.get('components', {}).get('review_targets', []),
            'review_status': item.review_status, 'human_reviewed': human,
            'human_review_complete': human and item.fact_id not in packet.review_required_fact_ids,
            'human_review': ({'action': latest.action, 'reviewer_id': latest.reviewer.reviewer_id,
                              'reason': latest.reason, 'version': latest.applied_version} if human else None),
            'specific_risk': risk, 'issues': issues, 'conflicts': conflicts,
            'recorded_review_required': item.fact_id in packet.review_required_fact_ids,
            'sealed_section': sealed_section, 'display_section': display_section,
            'plan_proposal': proposed_plan,
            **({'not_adopted_dimensions':record['adoption']['not_adopted_dimensions']}
                if record.get('adoption') else {}),
            'section_note': ('Extracted plan proposal; not a confirmed order or completed action. '
                             f'Original sealed SOAP section: {sealed_section}.') if proposed_plan else None,
        }
        facts.append(row)
        sections[display_section].append(row)
    return {
        'presentation_version': VERSION, 'packet_hash': packet.content_hash,
        'case_id': packet.case_id, 'version': packet.version, 'sections': sections,
        'summary': {
            'facts': len(facts), 'specific_risks': sum(f['specific_risk'] for f in facts),
            'machine_unverified': sum(f['machine_status'] in {'INSUFFICIENT_EVIDENCE', 'UNVERIFIED'} for f in facts),
            'machine_supported': sum(f['machine_status'] == 'SUPPORTED_BY_SOURCE' for f in facts),
            'human_reviewed': sum(f['human_reviewed'] for f in facts),
            'human_review_complete': sum(f['human_review_complete'] for f in facts),
            'recorded_review_required': len(packet.review_required_fact_ids),
        },
    }
