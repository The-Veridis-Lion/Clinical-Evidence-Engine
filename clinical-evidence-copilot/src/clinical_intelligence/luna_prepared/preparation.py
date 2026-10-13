"""Source indexing only: never rewrite source or assign clinical semantics."""
import re

HEADINGS = re.compile(
    r"(?im)^[ \t]*(?:#{1,6}[ \t]*)?(?:\*\*)?"
    r"(?P<label>History(?: of Present Illness)?|HPI|Physical Examination|Physical Exam|"
    r"Examination|PE|Past Medical History|Family History|Social History|"
    r"Review of Systems|ROS|Chief Complaint|Diagnosis|Diagnoses|Treatment|Laboratory Results|"
    r"Medications|Allergies|Assessment|Plan|Investigations|Results)"
    r"(?:\*\*)?[ \t]*(?::|(?=\r?$))")
ABBREVIATIONS = {"pt": "patient", "c/o": "complains of", "sx": "symptoms",
    "hx": "history", "resp": "respiratory", "uri": "upper respiratory infection",
    "uris": "upper respiratory infections", "sob": "shortness of breath",
    "bp": "blood pressure", "hr": "heart rate", "rr": "respiratory rate",
    "spo2": "oxygen saturation", "heent": "head, eyes, ears, nose and throat",
    "otc": "over-the-counter", "prn": "as needed", "am": "morning",
    "pm": "afternoon/evening", "wnl": "within normal limits"}


def section_kind(label):
    low = label.lower()
    if low in {"physical examination", "physical exam", "examination", "pe"}:
        return "physical_examination"
    if low in {"history", "history of present illness", "hpi"}:
        return "history"
    return low.replace(" ", "_")


def prepare(doc):
    doc.verify()
    text = doc.text
    headings = list(HEADINGS.finditer(text))
    sections = []
    if not headings or text[:headings[0].start()].strip():
        sections.append({"section_id": "section-000", "kind": "unsectioned",
            "label": None, "start": 0, "end": headings[0].start() if headings else len(text),
            "header": None})
    for i, match in enumerate(headings):
        sections.append({"section_id": f"section-{len(sections):03d}",
            "kind": section_kind(match['label']), "label": match['label'],
            "start": match.start(), "end": headings[i+1].start() if i+1 < len(headings) else len(text),
            "header": {"start": match.start(), "end": match.end(), "quote": match.group()}})
    passages = []
    for section in sections:
        # Heading is context metadata, not an assertion. Same-line content remains indexed.
        begin = section["header"]["end"] if section["header"] else section["start"]
        end = section["end"]
        boundaries = [begin]
        for match in re.finditer(r"\n|(?<=[.!?])[ \t]+(?=[A-Z])", text[begin:end]):
            point = begin + match.end()
            before = text[begin:begin+match.start()]
            # Keep common abbreviations and initials inside their original sentence.
            if "\n" not in match.group() and re.search(r"(?:\b(?:esp|e\.g|i\.e|Dr|Mr|Mrs|vs|approx|etc)|\b[A-Z])\.$", before, re.I):
                continue
            boundaries.append(point)
        boundaries.append(end)
        for start, stop in zip(boundaries, boundaries[1:]):
            while start < stop and text[start].isspace(): start += 1
            while stop > start and text[stop-1].isspace(): stop -= 1
            if start == stop: continue
            passages.append({"source_id": f"p{start:06d}-{stop:06d}", "start": start,
                "end": stop, "quote": text[start:stop], "section_id": section["section_id"],
                "section_kind": section["kind"]})
    glossary = []
    for token, expansion in ABBREVIATIONS.items():
        locations = [{"start": m.start(), "end": m.end(), "quote": m.group()}
            for m in re.finditer(r"(?<!\w)" + re.escape(token.upper() if token in {"am", "pm"} else token) + r"(?!\w)",
                text, 0 if token in {"am", "pm"} else re.I)]
        if locations: glossary.append({"abbreviation": token, "reading_aid": expansion, "occurrences": locations})
    # PND, CTS and other ambiguous abbreviations deliberately have no asserted expansion.
    return {"sections": sections, "source_catalogue": passages, "glossary": glossary,
        "context_policy": "Section labels describe documentation context only. Subject, reporting, time and uncertainty must be read from the original passages; none are inferred by preprocessing."}
