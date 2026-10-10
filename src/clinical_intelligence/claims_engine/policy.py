"""Policy selection is distinct from service identity and structured linkage."""


def policy_status():
    # The existing HbA1c module accepts constructed monitoring requests only.
    # No native service crosswalk/monitoring-purpose adapter is implemented.
    # A LOINC result in the encounter does not make a claim an HbA1c claim.
    return {
        "status": "POLICY_NOT_EVALUATED",
        "module": "NONE",
        "reason": "No explicitly supported native-claim policy adapter; source linkage alone does not establish policy applicability.",
        "specialized_module": "clinical_intelligence.claims_review (HbA1c monitoring; existing versioned constructed-request contract)",
        "payment_decision": "NOT_MADE",
    }
