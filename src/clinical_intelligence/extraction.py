"""LangExtract adapter: semantic source claims only, strictly exact source spans."""
from __future__ import annotations
import hashlib
import json
import re
from time import perf_counter
from pathlib import Path
from typing import Protocol
from .domain import (AssessmentClaim, ClinicalObservation, CorrectionRelationship,
                     DocumentExtraction, Patient, PlanClaim, RegisteredDocument, ServiceClaim, SourcePassage)
from .provider import Provider

class Extractor(Protocol):
    @property
    def key(self) -> str: ...
    def extract(self, document: RegisteredDocument) -> DocumentExtraction: ...


class ExtractionFailure(RuntimeError):
    def __init__(self, message, usage):
        super().__init__(message)
        self.usage = usage


class LangExtractExtractor:
    def __init__(self, provider: Provider):
        self.provider = provider
        self._baseline = json.loads((Path(__file__).parent / "contracts" / "baseline.json").read_text(encoding="utf-8"))

    def examples(self):
        import langextract as lx
        return [lx.data.ExampleData(text=text, extractions=[lx.data.Extraction(
            extraction_class=kind, extraction_text=text, attributes=attributes)
            for kind, attributes in rows]) for text, rows in self._baseline["examples"]]

    @property
    def key(self):
        import importlib.metadata
        payload = dict(self._baseline)
        payload.update(provider=self.provider.config.model_dump(), langextract=importlib.metadata.version("langextract"))
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def extract(self, document):
        started = perf_counter()
        self.provider.reset_usage()
        try:
            return self._extract(document)
        except Exception as error:
            usage = self.provider.usage(perf_counter() - started)
            usage.input_characters = len(document.text)
            if isinstance(error, json.JSONDecodeError) and usage.parse_failures == 0:
                usage.parse_failures = 1
            raise ExtractionFailure(str(error), usage) from error

    def _extract(self, document):
        import langextract as lx
        examples = self.examples()
        self.provider.reset_usage()
        start = perf_counter()
        model = self.provider.language_model(examples, document.text)
        # One semantic pass produces source claims; reconciliation happens later in code.
        result = lx.extract(text_or_documents=document.text, prompt_description=self._baseline["prompt"],
                            examples=examples, model=model, use_schema_constraints=False, extraction_passes=1,
                            max_char_buffer=max(10000, len(document.text) + 1), max_workers=1,
                            resolver_params={"suppress_parse_errors": False, "enable_fuzzy_alignment": False},
                            show_progress=False)
        classes = {"service": ServiceClaim, "plan": PlanClaim, "assessment": AssessmentClaim,
                   "observation": ClinicalObservation, "relationship": CorrectionRelationship}
        patient = None
        declared_id = None
        pending = []
        for extraction in result.extractions or []:
            attributes = extraction.attributes or {}
            if set(attributes) != {"data"} or not isinstance(attributes["data"], str):
                raise ValueError("Expected exactly one structured JSON data attribute")
            payload = json.loads(attributes["data"])
            if not isinstance(payload, dict):
                raise ValueError("Expected structured claim data object")
            # Explicit source identifiers can distinguish repeated verbatim evidence.
            context = {key: payload[key] for key in (
                "encounter_ref", "appointment_ref", "form_ref", "plan_ref",
                "target_encounter", "target_plan_ref") if isinstance(payload.get(key), str) and payload[key]}
            span = extraction.char_interval
            passage = locate_passage(document, extraction.extraction_text,
                                     span.start_pos if span else None, span.end_pos if span else None,
                                     context=context)
            if extraction.extraction_class == "patient":
                declared_id = payload.pop("declared_id", None)
                candidate = Patient.model_validate(payload)
                if patient is not None and candidate != patient:
                    raise ValueError("Multiple patient identities in one document are unsupported")
                patient = candidate
            else:
                if extraction.extraction_class not in classes:
                    raise ValueError(f"Unsupported claim class {extraction.extraction_class}")
                pending.append((extraction.extraction_class, payload, passage))
        if patient is None:
            raise ValueError("No grounded patient identity extracted")
        claims = {}
        for kind, payload, passage in pending:
            # Convert literal clock text in code; the model never calculates minutes.
            payload = normalize_clock_fields(kind, payload)
            # Identical payloads at the same source span share one claim identity.
            digest = hashlib.sha256((document.document_id + kind + json.dumps(payload, sort_keys=True)
                                     + str(passage.start) + str(passage.end)).encode()).hexdigest()[:24]
            claim = classes[kind](claim_id=digest, document_id=document.document_id, patient_id=patient.patient_id,
                                  passages=[passage], **payload)
            claims[digest] = claim
        usage = self.provider.usage(perf_counter() - start)
        usage.input_characters = len(document.text)
        usage.claim_counts = {kind: sum(c.kind == kind for c in claims.values())
                              for kind in sorted({c.kind for c in claims.values()})}
        return DocumentExtraction(document_id=document.document_id, extraction_key=self.key,
                                  declared_id=declared_id, patient=patient, claims=list(claims.values()),
                                  usage=usage)


def locate_passage(document: RegisteredDocument, quote: str, start: int | None, end: int | None,
                   *, context: dict[str, str] | None = None) -> SourcePassage:
    """Exact character verification, independent of library token-match labels.

    LangExtract jointly aligns ordered quotes; overlapping/out-of-order exact quotes
    can lose token alignment. A unique verbatim occurrence is still unambiguous evidence.
    Repeated occurrences require explicit identifiers in one blank-delimited section.
    No approximate match, whitespace normalization or reconstructed quotation is accepted.
    """
    locator = "langextract"
    if start is None or end is None or not (0 <= start < end <= len(document.text)) or document.text[start:end] != quote:
        candidates = []
        offset = document.text.find(quote) if quote else -1
        while offset >= 0:
            candidates.append(offset)
            offset = document.text.find(quote, offset + 1)
        locator = "unique_exact_substring"
        if len(candidates) > 1 and context:
            # Blank-line boundaries prevent context from leaking between source sections.
            boundaries = list(re.finditer(r"\r?\n[ \t]*\r?\n", document.text))
            supported = []
            for candidate in candidates:
                left = max((b.end() for b in boundaries if b.end() <= candidate), default=0)
                right = min((b.start() for b in boundaries if b.start() >= candidate + len(quote)), default=len(document.text))
                section = document.text[left:right]
                if all(re.search(r"(?<![\w-])" + re.escape(identifier) + r"(?![\w-])", section)
                       for identifier in context.values()):
                    supported.append(candidate)
            candidates = supported
        if len(candidates) != 1:
            raise ValueError(f"Evidence is absent or ambiguously located in the original document: {quote!r}")
        start, end = candidates[0], candidates[0] + len(quote)
    return SourcePassage(document_id=document.document_id, start=start, end=end, quote=quote,
                         line_start=document.text.count("\n", 0, start) + 1,
                         line_end=document.text.count("\n", 0, end - 1) + 1, locator=locator)


def clock_minutes(value: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value) is None:
        raise ValueError("Extractor must provide literal same-day HH:MM clock text")
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def normalize_clock_fields(kind: str, payload: dict) -> dict:
    payload = dict(payload)
    if kind == "service":
        for name in ("actual_intervals", "scheduled_intervals", "unspecified_intervals", "breaks"):
            payload[name] = [{"start": clock_minutes(i["start"]), "end": clock_minutes(i["end"])}
                             for i in payload.get(name, [])]
    elif kind == "relationship":
        for name in ("replacement_time", "original_time"):
            if payload.get(name) is not None:
                payload[name] = clock_minutes(payload[name])
    return payload
