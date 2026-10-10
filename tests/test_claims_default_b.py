from clinical_intelligence.claims_review.review import run_review
from clinical_intelligence.claims_review.note_extractor import note_request,extract_note,PROMPT
from clinical_intelligence.claims_review.note_prompt_b import PROMPT_B
from clinical_intelligence.claims_review.config import DEFAULT_NOTE_PROMPT
from b_candidate_validation import prepared
from test_b_candidate_validation import Fake, ROUND
import json

def test_public_and_low_level_defaults_capture_B():
    case,source=prepared(ROUND/'N05.json')
    rows=json.loads((ROUND/'expected.json').read_text())['cases']['N05']['correct_fixture']
    default=Fake(case,rows); explicit=Fake(case,rows); fallback=Fake(case,rows)
    pd=run_review(case,mode='fixture',provider=default)
    pb=run_review(case,mode='fixture',provider=explicit,note_prompt='B')
    pa=run_review(case,mode='fixture',provider=fallback,note_prompt='A')
    assert DEFAULT_NOTE_PROMPT=='B'
    assert default.requests[0]==explicit.requests[0]
    assert default.requests[0][0].startswith(PROMPT_B)
    assert fallback.requests[0][0].startswith(PROMPT)
    assert pd.identity['review_input_sha256']==pb.identity['review_input_sha256']
    assert pd.identity['review_input_sha256']!=pa.identity['review_input_sha256']
    assert pd.execution['note_prompt_selection']['note_prompt']=='B'
    assert note_request(source,{})[0].startswith(PROMPT_B)
    direct=Fake(case,rows)
    extract_note(direct,source,case.claim.model_dump(mode='json'),case.review_context.as_of)
    assert direct.requests[0][0].startswith(PROMPT_B)
