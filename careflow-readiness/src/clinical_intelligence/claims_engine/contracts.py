"""Native claim contracts; the specialized claims-review-prep/0.1 stays separate."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceRow(Record):
    source_id: str
    table: str
    data_record_number: int
    physical_line_start: int
    physical_line_end: int
    original_row_sha256: str
    source_file_sha256: str
    archive_sha256: str
    original_id: str | None
    patient_id: str | None
    encounter_id: str | None
    fields: dict[str, str]


class OriginalCode(Record):
    value: str
    system: str  # UNKNOWN is explicit; original strings are never crosswalked.
    system_basis: str
    source_id: str
    field: str


class EvidenceLink(Record):
    source_id: str
    role: str
    relationship: str
    proof_of_service: bool = False


class Diagnosis(Record):
    field: str
    code: OriginalCode
    evidence: list[EvidenceLink] = Field(default_factory=list)


class ServiceItem(Record):
    item_id: str  # source row identity, never an encounter or clinical event ID
    transaction_id: str
    charge_id: str
    source_id: str
    code: OriginalCode
    description: str
    from_date: str
    to_date: str
    units: str
    category: str
    identity_status: Literal["COMPOSITE_MATCH_UNIQUE", "AMBIGUOUS", "UNRESOLVED"]
    evidence: list[EvidenceLink]
    diagnosis_fields: list[str]
    issues: list[str]


class ClaimPacket(Record):
    schema_version: Literal["claim-evidence/1"] = "claim-evidence/1"
    archive_sha256: str
    claim_id: str
    claim_source_id: str
    patient_id: str
    patient_source_id: str | None
    patient_status: str
    original_encounter_id: str
    encounter_source_id: str | None
    encounter_status: str
    service_date: str
    items: list[ServiceItem]
    diagnoses: list[Diagnosis]
    transaction_source_ids: list[str]
    transaction_relationships: list[EvidenceLink]
    context: list[EvidenceLink]
    issues: list[str]
    missing_information: list[str]
    linkage_status: str
    review_readiness: str
    policy: dict[str, str]
    partition: str
    live_model_calls: Literal[0] = 0

    def referenced_sources(self) -> set[str]:
        refs = {self.claim_source_id, *self.transaction_source_ids}
        refs.update(x for x in [self.patient_source_id, self.encounter_source_id] if x)
        refs.update(x.source_id for x in self.context + self.transaction_relationships)
        for item in self.items:
            refs.update(x.source_id for x in item.evidence)
        for diagnosis in self.diagnoses:
            refs.update(x.source_id for x in diagnosis.evidence)
        return refs
