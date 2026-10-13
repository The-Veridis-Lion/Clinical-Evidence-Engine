"""App adapter: reuse exact Engine fact types and original turn indexing."""
from ..dialogue_first.contract import DialogueFact
from .source_adapter import source_index
from .models import EvidenceItem, digest


def ground_fact(raw, source):
    fact = DialogueFact.model_validate(raw)
    spans = [fact.evidence, *fact.supporting_evidence]
    indexed = source_index(source.document())
    evidence = []
    for span in spans:
        if not 0 <= span.start < span.end <= len(source.text) or source.text[span.start:span.end] != span.quote:
            raise ValueError('evidence quote/offset mismatch')
        turn = next((t for t in indexed['turns'] if t['start'] <= span.start and span.end <= t['end']), None)
        if turn is None:
            raise ValueError('evidence crosses a turn boundary')
        source_id = f"{turn['turn_id']}:{span.start}:{span.end}"
        evidence.append(EvidenceItem(evidence_id='e-' + digest([source.document_id, source.sha256, span.start, span.end])[:20],
            source_id=source_id, document_id=source.document_id, source_sha256=source.sha256,
            turn_id=turn['turn_id'], speaker_label=turn['speaker_label'], quote=span.quote,
            start=span.start, end=span.end, line_start=source.text.count('\n', 0, span.start)+1,
            line_end=source.text.count('\n', 0, span.end-1)+1, source_time=source.encounter_time))
    rebuilt = [dict(quote=e.quote, start=e.start, end=e.end, source_id=e.source_id,
                    document_id=e.document_id, turn_id=e.turn_id, speaker_label=e.speaker_label) for e in evidence]
    # Never accept a different document/turn/role hidden inside a plausible quotation.
    if fact.provenance and [p.model_dump() for p in fact.provenance] != rebuilt:
        raise ValueError('evidence provenance differs from original source')
    # Pydantic revalidates constructed provenance; engine assertions are preserved.
    fact = DialogueFact.model_validate({**fact.model_dump(), 'provenance': rebuilt})
    return fact, evidence
