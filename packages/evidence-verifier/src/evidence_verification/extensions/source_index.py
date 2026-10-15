"""Mechanical copilot-source-index/v1 catalogue shared with source consumers.

This migrates the existing Copilot index algorithm without changing its labels,
code-point offsets, IDs or sentence boundaries. It performs no role inference or
clinical entailment. The caller supplies its unchanged historical Engine index.
"""
import re

VERSION = 'copilot-source-index/v1'
NATIVE_LABELS = re.compile(r'(?<!\w)(Doctor|Patient|Nurse|Clinician|Physician|Provider):', re.I)


def source_index(doc, *, legacy_index):
    if doc.input_kind != 'dialogue' or re.search(r'\[(doctor|patient|nurse|clinician|physician|provider)\]', doc.text, re.I):
        return legacy_index(doc)
    labels = list(NATIVE_LABELS.finditer(doc.text))
    if not labels:
        return legacy_index(doc)
    doc.verify()
    boundaries = [m.start() for m in labels]
    if boundaries[0] != 0:
        boundaries.insert(0, 0)
    boundaries.append(len(doc.text))
    turns, catalogue = [], []
    for number, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1):
        label = next((m.group(0) for m in labels if m.start() == start), None)
        turn_id = f't{number:04d}'
        turns.append(dict(turn_id=turn_id, speaker_label=label, start=start, end=end, quote=doc.text[start:end]))
        body = start+len(label or '')
        stops = [body]+[body+m.end() for m in re.finditer(r'\n|(?<=[.!?])\s+(?=[A-Za-z])', doc.text[body:end])]+[end]
        for a, b in zip(stops, stops[1:]):
            while a < b and doc.text[a].isspace():
                a += 1
            while b > a and doc.text[b-1].isspace():
                b -= 1
            if a < b:
                catalogue.append(dict(source_id=f'{turn_id}:{a}:{b}', turn_id=turn_id,
                    speaker_label=label, start=a, end=b, quote=doc.text[a:b]))
    return {'turns': turns, 'source_catalogue': catalogue}
