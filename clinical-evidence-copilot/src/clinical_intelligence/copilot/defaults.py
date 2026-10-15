"""Versioned product choices; explicit historical request options remain replayable."""

# Promotion is an engineering decision backed by the frozen paired evidence.
# Explicit None/None retains the historical wire contract.
SEMANTICS_VERSION = 'clinical-fact-semantics/2'
TASK_VERSION = 'clinical-structured-extraction/1'
LOCAL_PROOF_ENABLED = False
SOURCE_DERIVATIONS_ENABLED = False
PROFILE_VERSION = 'copilot-default-profile/2'


def request_options():
    return {'semantics_version': SEMANTICS_VERSION, 'task_version': TASK_VERSION}
