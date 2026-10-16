"""Read-only draft display; reviewer decisions never become machine verification."""


VERSION = 'copilot-draft-presentation/4'


def retained_attributes(fact, proposal):
    attributes = proposal.get('attributes')
    return attributes if attributes is not None else (fact.attributes.model_dump() if fact.attributes else {})


def presentation_notes(fact, proposal):
    # A value and absent polarity can coexist legitimately. Do not adjudicate
    # their meaning, or translate the polarity into absence of the named object.
    if fact.polarity == 'absent' and retained_attributes(fact, proposal).get('value') is not None:
        return ['Polarity and value are retained separately; check the original source to determine what the negation applies to.']
    return []


def statement_text(fact, proposal):
    """Controlled prose from retained values, with no new clinical inference."""
    concept = fact.concept or 'an unnormalized source assertion'
    subject = {'patient': 'the patient', 'family': 'a family member',
               'other': 'another person', 'unknown': 'an unspecified subject'}[fact.experiencer]
    basis = proposal.get('reporting_basis', fact.assertion_basis)
    action = fact.category in {'medication', 'procedure', 'treatment'}
    valued_absence = bool(presentation_notes(fact, proposal))
    attrs = retained_attributes(fact, proposal)
    neutral_value = valued_absence and not action
    if action:
        # Action polarity can qualify execution, refusal, or documentation. It
        # cannot safely become "no [treatment]" or a newly inferred completion.
        if fact.temporality == 'planned':
            text = f'Planned for {subject}: {concept}'
        elif basis in {'patient_report', 'patient_reported'}:
            text = 'The patient reports ' + concept
            if fact.experiencer != 'patient':
                text += ' in ' + subject
        else:
            text = f'The source records {concept} for {subject}'
        if fact.clinical_status:
            text += f' with the recorded status “{fact.clinical_status}”'
        elif proposal.get('action_state') not in (None, 'unknown'):
            text += ' with the recorded action state “' + proposal['action_state'].replace('_', ' ') + '”'
        else:
            text += f' with polarity recorded as {fact.polarity}; the execution status is unspecified'
    elif valued_absence:
        value = str(attrs['value'])
        if attrs.get('unit') is not None:
            value += ' ' + str(attrs['unit'])
        text = f'The draft records a value of “{value}” for {concept} in {subject}'
    elif basis in {'patient_report', 'patient_reported'}:
        text = 'The patient reports ' + ({'absent': 'no ', 'uncertain': 'possible '}.get(fact.polarity, '')) + concept
        if fact.experiencer != 'patient':
            text += ' in ' + subject
    else:
        status = {'present': 'present', 'absent': 'explicitly absent', 'uncertain': 'uncertain'}[fact.polarity]
        text = f'The source describes {concept} as {status} for {subject}'
        if basis == 'discussion':
            text += ' in a discussion'
        elif basis == 'clinician_observation':
            text += ' as a clinician observation'
        elif basis == 'clinician_assessment':
            text += ' as a clinician assessment'
        elif basis == 'documented_history':
            text += ' in the documented history'
        else:
            text += '; the reporting basis is unspecified'
    text += {'historical': ' (historical)', 'planned': '' if action else ' (planned)',
             'unknown': ' (time scope unspecified)'}.get(fact.temporality, '')
    if attrs.get('duration') is not None:
        text += ' for ' + str(attrs['duration'])
    if attrs.get('frequency') is not None:
        text += ', with a recorded frequency of ' + str(attrs['frequency'])
    if attrs.get('severity') is not None:
        text += ', described as ' + str(attrs['severity'])
    if attrs.get('value') is not None:
        if not neutral_value:
            text += ', with a recorded value of ' + str(attrs['value'])
            if attrs.get('unit') is not None:
                text += ' ' + str(attrs['unit'])
    elif attrs.get('unit') is not None:
        text += ', with the unit recorded as ' + str(attrs['unit'])
    text += '.'
    if not action and fact.clinical_status and fact.clinical_status not in {'reported', 'reported absent', 'documented'}:
        text += f' The source describes this as “{fact.clinical_status}”.'
    elif not action and proposal.get('action_state') not in (None, 'unknown'):
        text += ' The draft describes this action as ' + proposal['action_state'].replace('_', ' ') + '.'
    if proposal.get('event_time') is not None:
        text += f' The recorded timing is “{proposal["event_time"]}”.'
    return text


def compact_statement(fact, proposal):
    """A short label from retained fields; no interpretation of clinical meaning."""
    concept = fact.concept or 'Unnormalized source assertion'
    attrs = retained_attributes(fact, proposal)
    action = fact.category in {'medication', 'procedure', 'treatment'}
    valued_absence = fact.polarity == 'absent' and attrs.get('value') is not None
    if action:
        # A negated action cannot safely be rewritten as no treatment.
        label = concept
        if fact.polarity != 'present':
            label += ' · negated action' if fact.polarity == 'absent' else ' · uncertain action'
    elif valued_absence:
        label = f'{concept} · negated'
    elif fact.polarity == 'absent':
        label = f'No {concept}'
    elif fact.polarity == 'uncertain':
        label = f'Possible {concept}'
    else:
        label = concept
    if fact.experiencer != 'patient':
        label = {'family': 'Family member', 'other': 'Other person',
                 'unknown': 'Subject unspecified'}[fact.experiencer] + ': ' + label
    details = []
    if fact.temporality == 'historical':
        details.append('historical')
    elif fact.temporality == 'planned':
        details.append('planned')
    elif fact.temporality == 'unknown':
        details.append('time unspecified')
    if action:
        state = proposal.get('action_state')
        if state not in (None, 'unknown'):
            if state != 'planned' or fact.temporality != 'planned':
                details.append(str(state).replace('_', ' '))
        elif fact.clinical_status:
            details.append(str(fact.clinical_status))
        else:
            details.append('execution unspecified')
        if proposal.get('completion_scope') not in (None, 'unknown'):
            details.append(str(proposal['completion_scope']).replace('_', ' '))
    elif fact.category == 'diagnosis' and fact.polarity != 'absent' and fact.clinical_status:
        details.append(str(fact.clinical_status))
    if attrs.get('severity') is not None:
        details.append(str(attrs['severity']))
    if attrs.get('value') is not None:
        value = str(attrs['value'])
        if attrs.get('unit') is not None:
            value += ' ' + str(attrs['unit'])
        details.append(value)
    elif attrs.get('unit') is not None:
        details.append(str(attrs['unit']))
    value_text = str(attrs['value']).casefold() if attrs.get('value') is not None else ''
    for key in ('duration', 'frequency'):
        if attrs.get(key) is not None and not (len(str(attrs[key])) >= 6 and str(attrs[key]).casefold() in value_text):
            details.append(str(attrs[key]))
    if proposal.get('event_time') is not None and not (len(str(proposal['event_time'])) >= 6
                                                      and str(proposal['event_time']).casefold() in value_text):
        details.append(str(proposal['event_time']))
    return ' · '.join((label, *details))


def summary_group(fact, section):
    """Navigation grouping from existing typed fields, not a new clinical label."""
    if section == 'S':
        if fact.category == 'medication':
            return 'Medications'
        if (fact.category in {'diagnosis', 'condition'} or fact.temporality == 'historical'
                or fact.assertion_basis == 'documented_history'):
            return 'History'
        if fact.category == 'symptom' and fact.polarity == 'absent':
            return 'ROS'
        return 'HPI'
    return {'O': 'Findings', 'A': 'Assessment', 'P': 'Plan'}[section]


def summary_priority(fact, proposal, risk):
    """Stable UI sorting hint from fields already retained in the draft."""
    attrs = retained_attributes(fact, proposal)
    measured = attrs.get('unit') is not None
    if attrs.get('severity') is not None:
        measured = measured or any(char.isdigit() for char in str(attrs['severity']))
    if attrs.get('value') is not None:
        measured = measured or any(char.isdigit() for char in str(attrs['value']))
    if risk:
        return 4
    if (fact.category in {'medication', 'laboratory_result'} or measured
            or fact.category == 'symptom' and attrs.get('duration') is not None
            or fact.category in {'diagnosis', 'condition'} and fact.polarity != 'absent'):
        return 3
    if attrs.get('duration') is not None or attrs.get('severity') is not None:
        return 2
    return 1


def relationship_presentation(packet):
    """Expose retained relation proposals without creating clinical assertions."""
    rows = []
    for rank, item in enumerate(packet.relationships):
        original = item.get('original', {})
        if not isinstance(original, dict):
            original = {}
        endpoints = []
        for side in ('from', 'to'):
            index = original.get(side + '_fact_index')
            # Accepted facts may have gaps in their original extraction indices.
            # Historic packets do not always carry an explicit index mapping.
            resolved = (not packet.rejected_facts and type(index) is int
                        and 0 <= index < len(packet.facts))
            fact = packet.facts[index] if resolved else None
            endpoints.append({'input_index': index, 'fact_id': fact.fact_id if fact else None,
                'original_concept': fact.original_fact.get('concept') if fact else None,
                'current_concept': fact.assertion.concept if fact else None,
                'resolution': 'resolved_original_index' if fact else 'unresolved_original_index'})
        left, right = endpoints
        self_reference = (type(left['input_index']) is int and left['input_index'] == right['input_index'])
        structural_status = ('SELF_REFERENCE' if self_reference else
            'ENDPOINTS_DISTINCT' if all(e['fact_id'] for e in endpoints) else 'UNRESOLVED_ENDPOINT')
        concern = ('Both endpoints name the same input fact. This self-reference cannot establish a relation between distinct facts.'
                   if self_reference else 'Original endpoint identity cannot be resolved safely from this packet.'
                   if structural_status == 'UNRESOLVED_ENDPOINT' else None)
        citations = []
        for citation_rank, span in enumerate(original.get('provenance', [])):
            if not isinstance(span, dict):
                continue
            start, end = span.get('start'), span.get('end')
            exact = (type(start) is int and type(end) is int and 0 <= start < end <= len(packet.source.text)
                     and packet.source.text[start:end] == span.get('quote')
                     and span.get('document_id') in (None, packet.source.document_id))
            citations.append({**span, 'span_id': f'relation-span-{rank}-{citation_rank}', 'source_match': exact})
        rows.append({'relationship_id': item.get('relationship_id', f'relationship-{rank}'),
            'relation': original.get('relation'), 'from': left, 'to': right,
            'status': item.get('status', 'unreviewed'),
            'adopted_in_soap': item.get('adopted_in_soap', False),
            'structural_status': structural_status, 'structural_concern': concern,
            'interpretation': 'Retained relationship proposal; clinical meaning is unverified.',
            'citations': citations, 'original_proposal': original})
    return rows


def source_navigation(packet):
    """Expose original record order independently of citation and event order."""
    from .source_adapter import source_index, speaker_annotations
    annotations = speaker_annotations(packet.source.document())
    index = source_index(packet.source.document())
    turns = index['turns']
    raw = annotations or turns
    segments = []
    if raw and raw[0]['start'] > 0:
        segments.append({'start': 0, 'end': raw[0]['start'], 'raw_speaker_label': None})
    for row in raw:
        segments.append({'start': row['start'], 'end': row['end'],
                         'raw_speaker_label': row.get('raw_label', row.get('speaker_label'))})
    for rank, row in enumerate(segments, 1):
        row['record_order'] = rank
        row['segment_id'] = f'source-record-{rank}'
    evidence = []
    for item in packet.evidence:
        matches = [i for i, row in enumerate(segments) if row['start'] < item.end and item.start < row['end']]
        first, last = (matches[0], matches[-1]) if matches else (0, len(segments) - 1)
        evidence.append({**item.model_dump(mode='json'),
            'record_orders': [segments[i]['record_order'] for i in matches],
            'raw_speaker_labels': list(dict.fromkeys(segments[i]['raw_speaker_label'] for i in matches)),
            'context_start': segments[max(0, first - 1)]['start'] if segments else 0,
            'context_end': segments[min(len(segments) - 1, last + 1)]['end'] if segments else len(packet.source.text)})
    return {'segments': segments, 'evidence': evidence,
            'available_passages': index['source_catalogue'],
            'encounter_time': packet.source.encounter_time,
            'offset_unit': packet.source.offset_unit}


def draft_presentation(packet):
    """Project retained fields for readers without changing the sealed packet."""
    packet.verify()
    return _draft_presentation_verified(packet)


def _draft_presentation_verified(packet):
    """Project a packet already verified by the saved CaseStore read."""
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
                     and set(latest.evidence_ids) == set(item.evidence_ids)
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
            'display_text': statement_text(fact, proposal),
            'compact_text': compact_statement(fact, proposal),
            'category': fact.category, 'summary_group': summary_group(fact, display_section),
            'summary_priority': summary_priority(fact, proposal, risk),
            'presentation_notes': presentation_notes(fact, proposal),
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
        'relationship_proposals': relationship_presentation(packet),
        'source_navigation': source_navigation(packet),
        'summary': {
            'facts': len(facts), 'specific_risks': sum(f['specific_risk'] for f in facts),
            'machine_unverified': sum(f['machine_status'] in {'INSUFFICIENT_EVIDENCE', 'UNVERIFIED'} for f in facts),
            'machine_supported': sum(f['machine_status'] == 'SUPPORTED_BY_SOURCE' for f in facts),
            'human_reviewed': sum(f['human_reviewed'] for f in facts),
            'human_review_complete': sum(f['human_review_complete'] for f in facts),
            'recorded_review_required': len(packet.review_required_fact_ids),
        },
    }
