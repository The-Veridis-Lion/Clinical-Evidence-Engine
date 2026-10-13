"""Bounded terminology/date grounding, never diagnosis or event inference."""
import re
import unicodedata
from datetime import datetime

VERSION = 'claims-review-grounding/1'
LOINC_URL = 'https://loinc.org/4548-4/'
CMS_URL = 'https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?NCDid=100'

# Local, reviewed concept vocabulary; these phrase mappings do NOT establish
# specimen, units, method, or the full LOINC observation code.
TERMS = [
    ('hba1c', r'\b(?:Hb\s*A1c|Hgb\s*A1c|ha?emoglobin\s+A1c|A1c)\b', 'exact_synonym', LOINC_URL),
    ('glycated_hemoglobin', r'\b(?:glycated|glycosylated)\s+ha?emoglobin\b', 'contextual_family', CMS_URL),
    ('other_glycated_protein', r'\b(?:glycated\s+(?:albumin|protein)|fructosamine)\b', 'different_concept', CMS_URL),
]


def terminology(text):
    mentions = []
    for concept, pattern, status, basis in TERMS:
        for match in re.finditer(pattern, text, re.I):
            mentions.append(dict(original_phrase=match.group(), start=match.start(), end=match.end(),
                                 concept=concept, mapping_status=status, mapping_basis=basis,
                                 code_system=None, code=None))
    for match in re.finditer(r'\bLOINC\s*:?\s*4548-4\b',text,re.I):
        mentions.append(dict(original_phrase=match.group(),start=match.start(),end=match.end(),concept='hba1c',
                             mapping_status='verified_code',mapping_basis=LOINC_URL,code_system='LOINC',code='4548-4'))
    return {'version': VERSION, 'mentions': sorted(mentions, key=lambda m: m['start']),
            'status': 'recognized' if mentions else 'unresolved',
            'limit': 'Phrase presence does not prove assertion polarity, intent, performance or scope.'}


def supports_monitoring_test(text):
    return any(m['concept'] in {'hba1c', 'glycated_hemoglobin'} for m in terminology(text)['mentions'])


def explicit_dates(text):
    """Unambiguous complete dates only; no day/month convention guessing."""
    found = []
    patterns = [
        (r'\b\d{4}-\d{2}-\d{2}\b', ['%Y-%m-%d']),
        (r'\b\d{4}/\d{1,2}/\d{1,2}\b', ['%Y/%m/%d']),
        (r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b', ['%B %d %Y', '%b %d %Y']),
        (r'\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b', ['%d %B %Y', '%d %b %Y']),
    ]
    for pattern, formats in patterns:
        for m in re.finditer(pattern, text, re.I):
            token = re.sub(r'\s+', ' ', m.group().replace(',', ''))
            for fmt in formats:
                try:
                    day = datetime.strptime(token, fmt).date()
                    found.append({'original_phrase': m.group(), 'date': day.isoformat(), 'start': m.start(), 'end': m.end()})
                    break
                except ValueError:
                    pass
    return found


def comparable(text):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', text)).casefold().strip()


def provider_grounded(provider, text):
    return comparable(provider) in comparable(text)


def authentication(provider, text):
    """Positive/negative textual declarations with provider on that same line.

    Does not certify signature authenticity or authority over another source.
    Mixed declarations remain unresolved. Scope still requires semantic review.
    """
    positive = negative = False
    for line in text.splitlines():
        if not provider_grounded(provider, line):
            continue
        neg = bool(re.search(r'\b(?:not\s+(?:signed|authenticated)|unsigned|unauthenticated)\b', line, re.I))
        pos = bool(re.search(r'\b(?:signed|authenticated|digital signature|electronic signature|e-signed)\b', line, re.I))
        negative |= neg
        positive |= pos and not neg
    return True if positive and not negative else False if negative and not positive else None
