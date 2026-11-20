"""Offline evaluation against annotated source spans. This command makes no requests."""
import argparse
from collections import Counter
import json
from pathlib import Path

from components.structure_contract import structure_map, validate_ai


def node_key(node):
    return node['role'], tuple((span['start'], span['end']) for span in node['spans'])


def edge_keys(result):
    nodes = {node['id']: node_key(node) for node in result['nodes']}
    return {(nodes[edge['sourceId']], nodes[edge['targetId']], edge['type'], edge['direction']) for edge in result['relations']}


def tally(counts, predicted, expected):
    counts.update(tp=len(predicted & expected), fp=len(predicted - expected), fn=len(expected - predicted))


def rates(counts):
    tp, fp, fn = (counts[key] for key in ('tp', 'fp', 'fn'))
    return {'tp': tp, 'fp': fp, 'fn': fn, 'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


def evaluate(dataset, predictions):
    totals = {role: Counter() for role in ('CLAIM', 'EVIDENCE', 'RELATION')}
    grounding = Counter()
    for case in dataset['cases']:
        text = case['text']
        mapping, _ = structure_map(text)
        sentences = mapping['sentences']
        ids = {row['id'] for row in sentences}
        gold = validate_ai(case['gold'], text, sentences, ids)
        raw = predictions.get(case['id'])
        try:
            found = validate_ai(raw, text, sentences, ids)
            grounding['validResponses'] += 1
        except ValueError:
            # The production validator stores no part of a failed response.
            found = {'nodes': [], 'relations': []}
        for role in ('CLAIM', 'EVIDENCE'):
            tally(totals[role], {node_key(node) for node in found['nodes'] if node['role'] == role},
                  {node_key(node) for node in gold['nodes'] if node['role'] == role})
        tally(totals['RELATION'], edge_keys(found), edge_keys(gold))
        if not isinstance(raw, dict) or not isinstance(raw.get('nodes'), list):
            grounding['missingOrUnreadable'] += 1
            continue
        for node in raw['nodes']:
            grounding['returnedCandidates'] += 1
            anchors = node.get('spans', []) if isinstance(node, dict) else []
            try:
                validate_ai({'nodes': [node], 'relations': []}, text, sentences, ids)
                grounding['validCandidates'] += 1
            except ValueError as error:
                if str(error) in ('AI_SPAN_INVALID', 'AI_SENTENCE_INVALID'):
                    grounding['ungroundedCandidates'] += 1
            if not isinstance(anchors, list):
                continue
            for anchor in anchors:
                grounding['returnedAnchors'] += 1
                # Count each literal anchor independently from node and edge decisions.
                candidate = {'id': 'anchor', 'role': 'CLAIM', 'basis': 'UNCERTAIN', 'spans': [anchor]}
                try:
                    validate_ai({'nodes': [candidate], 'relations': []}, text, sentences, ids)
                    grounding['validAnchors'] += 1
                except ValueError:
                    pass
    size = len(dataset['cases'])
    anchors, candidates = grounding['returnedAnchors'], grounding['returnedCandidates']
    return {'classification': dataset['classification'], 'cases': size,
            'scores': {role: rates(count) for role, count in totals.items()}, 'validation': dict(grounding),
            'responseValidationRate': grounding['validResponses'] / size if size else None,
            'spanValidationRate': grounding['validAnchors'] / anchors if anchors else None,
            'ungroundedCandidateRate': grounding['ungroundedCandidates'] / candidates if candidates else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--predictions', type=Path, help='Object mapping case IDs to raw structure responses')
    parser.add_argument('--self-check', action='store_true', help='Use labels as inputs to test the evaluator only')
    args = parser.parse_args()
    if bool(args.predictions) == args.self_check:
        parser.error('Specify either --predictions or --self-check')
    dataset = json.loads(args.dataset.read_text(encoding='utf-8'))
    ids = [case['id'] for case in dataset['cases']]
    if not ids or len(set(ids)) != len(ids):
        parser.error('Unique case IDs are required')
    predictions = ({case['id']: case['gold'] for case in dataset['cases']} if args.self_check
                   else json.loads(args.predictions.read_text(encoding='utf-8')))
    if not isinstance(predictions, dict) or set(predictions) - set(ids):
        parser.error('Unexpected prediction case IDs')
    print(json.dumps({'selfCheck': args.self_check, **evaluate(dataset, predictions)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
