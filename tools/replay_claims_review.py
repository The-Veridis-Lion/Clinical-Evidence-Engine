"""Replay saved valid proposals through current code; never make a model call."""
import argparse
import json
from pathlib import Path
from clinical_intelligence.claims_review.contracts import CaseInput, ReviewPacket
from clinical_intelligence.claims_review.prepare import digest
from clinical_intelligence.claims_review.review import run_review


class ReplayProvider:
    def __init__(self, responses):
        self.responses = iter(responses)

    def structured_output(self, prompt, schema, *, purpose):
        return next(self.responses)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, default=Path('examples/claims_review/development'))
    parser.add_argument('--packets', type=Path, required=True)
    parser.add_argument('--traces', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    responses = {}
    for path in args.traces.glob('call-*/answer.json'):
        value = json.loads(path.read_text(encoding='utf-8'))
        responses[digest(value)] = value
    args.output.mkdir(parents=True, exist_ok=True)
    for path in sorted(args.cases.glob('DEV-*.json')):
        case = CaseInput.model_validate_json(path.read_text(encoding='utf-8'))
        original = ReviewPacket.model_validate_json((args.packets / path.name).read_text(encoding='utf-8'))
        if original.preparation['input_sha256'] != digest(case.model_dump(mode='json')):
            raise ValueError('Replay input differs from recorded live input')
        if any(n['status'] != 'completed' for n in original.execution['note_sources']):
            raise ValueError('This narrow replay requires saved validated proposals, not failed selections')
        selected = [responses[n['proposal_sha256']] for n in original.execution['note_sources']]
        packet = run_review(case, mode='fixture', provider=ReplayProvider(selected), input_label=str(path))
        packet.execution['replay'] = {'original_packet': str(args.packets / path.name),
                                      'original_identity': original.identity,
                                      'type': 'offline_saved_response_replay_not_new_model_measurement'}
        (args.output / path.name).write_text(packet.model_dump_json(indent=2) + '\n', encoding='utf-8')
        print(path.stem, packet.status)


if __name__ == '__main__':
    main()
