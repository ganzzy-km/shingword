import io
import json
import threading
import time
from copy import deepcopy

import pytest
from v2_fixture import v2app, user_client
from app.analysis.quotation import extract_quotations
from components.structure_contract import structure_map, validate_ai, validate_paragraph_ai, compare_structures
from app.extensions import db
from app.models import Analysis, AppSetting, EssayStructureMap, EssayStructureRun
from app.services.secrets_service import MemorySecretStore
from app.v2.baze_provider import BazeProvider, GatewaySettings


CLAIM = '😀 학교에 독서 시간이 필요하다.'
BODY = CLAIM + '\n학교에 독서 시간이 필요하다.\n\n친구들은 “하루 ‘십 분’부터 시작했다”고 말했다.'
BASE = 'https://factchat-cloud.mindlogic.ai/v1/gateway'
POLICY = 'test-structure-1'


def node(identifier, role, *anchors):
    return {'id': identifier, 'role': role, 'basis': 'EXPLICIT', 'spans': [
        {'sentenceId': sid, 'text': text, 'occurrence': occurrence} for sid, text, occurrence in anchors]}


def anchor(pid, text, occurrence=1):
    return {'paragraphId': pid, 'text': text, 'occurrence': occurrence}


def paragraph_node(identifier, role, *anchors):
    return {'id': identifier, 'role': role, 'basis': 'EXPLICIT', 'spans': list(anchors)}


def response():
    return {'nodes': [paragraph_node('c', 'CLAIM', anchor('p1', CLAIM)),
                      paragraph_node('e', 'EVIDENCE', anchor('p2', '‘십 분’'))],
            'relations': [{'sourceId': 'e', 'targetId': 'c', 'type': 'SUPPORTS', 'basis': 'IMPLICIT'}],
            'quotations': [anchor('p2', '“하루 ‘십 분’부터 시작했다”'), anchor('p2', '‘십 분’')]}


class Gateway:
    def __init__(self):
        self.requests = []
        self.value = response()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.failure = None

    def open(self, req, timeout):
        self.requests.append((json.loads(req.data), timeout))
        self.entered.set()
        assert self.release.wait(5)
        if self.failure:
            raise self.failure
        class Answer(io.BytesIO):
            status = 200
            headers = {'X-Credits-Charged': '0.012'}

            def geturl(self):
                return req.full_url
        return Answer(json.dumps({'model': 'synthetic-structure', 'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.value)}}],
            'usage': {'prompt_tokens': 410, 'completion_tokens': 112, 'total_tokens': 522}}).encode())


def test_structure_captures_billing_and_keeps_exact_anchors_required():
    class GatewayWithBilling:
        def open(self, req, timeout):
            payload = json.loads(req.data)
            prompt = payload['messages'][0]['content']
            assert 'exact nonempty original text in one supplied paragraph' in prompt
            assert 'Include complete nested quotations individually' in prompt
            reply = {'model': 'synthetic-structure', 'billing': {'deducted_credit': 1.2054},
                     'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps({
                         'nodes': [paragraph_node('e', 'EVIDENCE', anchor('p2', '"하루 \'십 분\'부터 시작했다"'))],
                         'relations': [], 'quotations': []})}}]}

            class Answer(io.BytesIO):
                status = 200
                headers = {}

                def geturl(self):
                    return req.full_url

            return Answer(json.dumps(reply).encode())

    mapping, quotes = structure_map(BODY)
    rows = mapping['paragraphs']
    paragraphs = [{'id': row['id'], 'text': BODY[row['start']:row['end']]} for row in rows]
    provider = BazeProvider(GatewaySettings(BASE, 'synthetic-structure', 512, 512, 3),
        MemorySecretStore({'BAZE_API_KEY': 'synthetic-key'}), opener=GatewayWithBilling())
    value, usage = provider.structure(paragraphs)
    assert usage['creditsCharged'] == '1.2054'
    allowed = {row['id'] for row in rows}
    with pytest.raises(ValueError, match='AI_SPAN_INVALID'):
        validate_paragraph_ai(value, BODY, mapping, quotes, allowed)
    value['nodes'][0]['spans'] = [anchor('p1', BODY[:rows[0]['end']])]
    verified = validate_paragraph_ai(value, BODY, mapping, quotes, allowed)
    assert verified['nodes'][0]['spans'] == [{'paragraphId': 'p1', 'start': 0, 'end': rows[0]['end']}]


@pytest.fixture
def gateway(v2app):
    gateway = Gateway()
    v2app.config.update(AI_STRUCTURE_ENABLED=True, AI_STRUCTURE_POLICY_VERSION=POLICY, GEULBIT_S4_ENGINE=True,
        EXTERNAL_AI_TERMS_APPROVED=True, ANALYSIS_SYNCHRONOUS=True, AI_STRUCTURE_CALL_COST_UNITS=3,
        AI_LIMITS={'dailyRequests': 5, 'monthlyBudgetUnits': 20, 'callCostUnits': 1, 'cooldownSeconds': 0, 'concurrency': 2})
    v2app.extensions['structure_provider'] = BazeProvider(GatewaySettings(BASE, 'synthetic-structure', 1024, 6000, 3),
        MemorySecretStore({'BAZE_API_KEY': 'synthetic-secret-not-for-logs'}), opener=gateway)
    with v2app.app_context():
        db.session.merge(AppSetting(key='ai_enabled', value=True)); db.session.commit()
    yield gateway
    gateway.release.set()


def test_stack_exact_intervals_nested_unicode_multiple_and_escape():
    body = '😀 “바깥 ‘안😀’ 끝”과 "두 번째 \'셋\'" 그리고 \\"문자\\"와 don\'t, don’t, James\' 책.'
    quotes = extract_quotations(body, include_unresolved=True)
    assert [q.text for q in quotes] == ['바깥 ‘안😀’ 끝', '안😀', "두 번째 '셋'", '셋']
    assert [q.quote_type for q in quotes] == ['curly_double', 'curly_single', 'straight_double', 'straight_single']
    assert [q.depth for q in quotes] == [0, 1, 0, 1]
    assert [q.parent_id for q in quotes] == [None, quotes[0].quote_id, None, quotes[2].quote_id]
    for q in quotes:
        assert q.raw == q.opener + q.text + q.closer
        assert (q.start, q.end) == (body.index(q.raw), body.index(q.raw) + len(q.raw))
        assert body[q.content_start:q.content_end] == q.text and q.status == 'CLOSED'
    even = r'\\"실제 인용"'
    assert extract_quotations(even)[0].start == 2


@pytest.mark.parametrize('body,expected', [
    ('“미완성', ['UNCLOSED']), ('잘못 ” 끝', ['UNMATCHED_CLOSE']),
    ('“겉 ‘안” 닫힘’', ['MISMATCHED', 'MISMATCHED', 'UNMATCHED_CLOSE', 'UNMATCHED_CLOSE']),
    ('"겉 "안" 끝"', ['AMBIGUOUS', 'AMBIGUOUS']), ('“열림 ’ 닫힘”', ['MISMATCHED', 'UNMATCHED_CLOSE']),
])
def test_unresolved_has_no_fabricated_content_or_legacy_protection(body, expected):
    ranges = extract_quotations(body, include_unresolved=True)
    assert [q.status for q in ranges] == expected
    assert all(q.end == q.start + 1 and q.text == '' for q in ranges)
    assert extract_quotations(body) == []


def test_stack_long_and_deep():
    phrase = '😀 “말 ‘안’ 끝” 반복. '
    body = phrase * 24000
    started = time.perf_counter()
    found = extract_quotations(body)
    assert len(found) == 48000 and found[-1].start == len(phrase) * 23999 + phrase.index('‘')
    deep = extract_quotations('“' * 16000 + '끝' + '”' * 16000)
    assert deep[-1].depth == 15999 and deep[-1].text == '끝' and deep[0].end == 32001
    assert time.perf_counter() - started < 5


def essay(client, headers, text=BODY):
    res = client.post('/api/writings', headers=headers, json={'title': '비공개 제목', 'work': '비공개 작품',
        'inquiryQuestion': '비공개 탐구 질문', 'content': text})
    assert res.status_code == 201
    return res.json['data']


def s4(client, headers, writing):
    res = client.post('/api/analyses', headers=headers, json={'writingId': writing['id'],
        'revisionNumber': writing['revisionNumber'], 'content': writing['content']})
    assert res.status_code == 202
    ids = res.json['data']
    assert client.get('/api/analysis-jobs/' + ids['jobId']).json['data']['status'] == 'completed'
    return ids['analysisId'], '/api/writing-versions/' + ids['essayVersionId'] + '/structure'


def freeze(client, headers, writing):
    version = client.post('/api/writings/' + writing['id'] + '/versions', headers=headers,
                          json={'revisionNumber': writing['revisionNumber']})
    assert version.status_code == 201
    return '/api/writing-versions/' + version.json['data']['id'] + '/structure'


def consent(client, headers, granted=True):
    assert client.post('/api/structure/consent', headers=headers,
                       json={'granted': granted, 'policyVersion': POLICY}).status_code == 200


def reviewed(client, headers, path, excluded=None):
    excluded = excluded or []
    res = client.post(path + '/preview', headers=headers, json={'excludeParagraphIds': excluded})
    assert res.status_code == 200, res.json
    return {'excludeParagraphIds': excluded, 'reviewed': True, 'previewHash': res.json['data']['previewHash']}, res.json['data']


def await_run(client, path, rid):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        req = client.get(path + '/ai/' + rid)
        assert req.status_code == 200
        data = req.json['data']
        if data['status'] not in ('QUEUED', 'RUNNING'):
            return data
        time.sleep(.04)
    pytest.fail('AI job exceeded test deadline')


def test_http_independence_grounding_comparison_and_saved_result(v2app, gateway):
    client, headers, uid = user_client(v2app)
    writing = essay(client, headers)
    analysis_id, path = s4(client, headers, writing)
    before = client.get('/api/analyses/' + analysis_id).json['data']
    data, _ = reviewed(client, headers, path)
    assert client.post(path + '/ai', headers=headers, json=data).status_code == 403
    assert gateway.requests == []
    consent(client, headers)
    started = client.post(path + '/ai', headers=headers, json=data)
    assert started.status_code == 202, started.json
    saved = await_run(client, path, started.json['data']['id'])
    assert saved['status'] == 'COMPLETED', saved
    assert saved['inputUnit'] == 'paragraph' and saved['promptVersion'] == 'structure-paragraphs/4'
    assert saved['result']['paragraphs'] == [
        {'paragraphId': 'p1', 'claimCount': 1, 'evidenceCount': 0, 'quotationCount': 0},
        {'paragraphId': 'p2', 'claimCount': 0, 'evidenceCount': 1, 'quotationCount': 2},
    ]
    assert [BODY[q['start']:q['end']] for q in saved['result']['quotations']] == ['“하루 ‘십 분’부터 시작했다”', '‘십 분’']
    assert saved['result']['spanValidation'] == 'VERIFIED' and saved['usage']['total_tokens'] == 522
    assert saved['usage']['creditsCharged'] == '0.012' and saved['reservedCostUnits'] == 3
    evidence = saved['result']['nodes'][1]['spans'][0]
    assert BODY[evidence['start']:evidence['end']] == '‘십 분’'
    view = client.get(path + '?analysisId=' + analysis_id).json['data']
    assert view['versionStatus'] == 'CURRENT' and view['comparison']['nodes'] and len(view['quotations']) == 2
    assert view['sentences'][0]['id'] == 's1' and view['sentences'][2]['id'] == 's3'
    assert view['ai']['result'] == saved['result'] and view['s4']['engine'] == 'S4'
    cached = client.post(path + '/ai', headers=headers, json=data)
    assert cached.status_code == 200 and cached.json['data']['cached'] and len(gateway.requests) == 1
    payload, timeout = gateway.requests[0]
    assert payload['response_format']['json_schema']['strict'] is True and timeout == 3
    outbound = json.loads(payload['messages'][1]['content'])
    assert outbound == {'paragraphs': [{'id': 'p1', 'text': BODY.split('\n\n')[0]},
                                       {'id': 'p2', 'text': BODY.split('\n\n')[1]}]}
    raw = json.dumps(payload, ensure_ascii=False)
    for value in (uid, writing['id'], analysis_id, '비공개', 'DIRECT_QUOTE', 'synthetic-secret-not-for-logs'):
        assert value not in raw
    with v2app.app_context():
        row = db.session.get(EssayStructureRun, saved['id'])
        mapping = db.session.get(EssayStructureMap, row.version_id)
        assert mapping.sentence_map and len(mapping.quotation_ranges) == 2
        assert db.session.get(Analysis, analysis_id).result_snapshot == before['result']
    assert client.get('/api/analyses/' + analysis_id).json['data'] == before
    other, other_headers, _ = user_client(v2app, 'other')
    assert other.get(path).status_code == 404
    assert other.get(path + '/ai/' + saved['id']).status_code == 404
    assert other.post(path + '/ai', headers=other_headers, json=data).status_code == 404
    updated = client.patch('/api/writings/' + writing['id'], headers=headers,
                           json={'revisionNumber': writing['revisionNumber'], 'content': BODY + ' 고친 판본.'}).json['data']
    assert client.get(path).json['data']['versionStatus'] == 'STALE'
    assert client.post(path + '/ai', headers=headers, json=data).status_code == 409
    new_path = freeze(client, headers, updated)
    assert new_path != path and client.get(new_path).json['data']['ai'] is None
    assert client.get(new_path + '?analysisId=' + analysis_id).status_code == 404
    assert client.get(new_path + '/ai/' + saved['id']).status_code == 404
    assert client.delete('/api/writings/' + writing['id'], headers=headers,
                         json={'confirmation': writing['title']}).status_code == 200
    with v2app.app_context():
        assert EssayStructureRun.query.count() == EssayStructureMap.query.count() == 0


@pytest.mark.parametrize('change,code', [('id', 'AI_PARAGRAPH_INVALID'), ('span', 'AI_SPAN_INVALID'),
    ('quote', 'AI_QUOTATION_INVALID'), ('edge', 'AI_RELATION_INVALID'), ('schema', 'AI_SCHEMA_INVALID'),
    ('duplicate', 'AI_NODE_INVALID')])
def test_bad_provider_result_is_rejected(v2app, gateway, change, code):
    client, headers, _ = user_client(v2app)
    path = freeze(client, headers, essay(client, headers))
    consent(client, headers)
    if change == 'id': gateway.value['nodes'][0]['spans'][0]['paragraphId'] = 'p90'
    if change == 'span': gateway.value['nodes'][0]['spans'][0]['text'] = '없는 원문'
    if change == 'quote': gateway.value['quotations'][0] = anchor('p1', CLAIM)
    if change == 'edge': gateway.value['relations'][0]['targetId'] = 'ghost'
    if change == 'schema': gateway.value['summary'] = 'unsupported'
    if change == 'duplicate': gateway.value['nodes'].append({**deepcopy(gateway.value['nodes'][0]), 'id': 'd'})
    data, _ = reviewed(client, headers, path)
    started = client.post(path + '/ai', headers=headers, json=data)
    assert started.status_code == 202
    result = await_run(client, path, started.json['data']['id'])
    assert result['status'] == 'REVIEW_REQUIRED' and result['errorCode'] == code and result['result'] is None


def test_privacy_preview_and_match_only_link(v2app, gateway):
    client, headers, uid = user_client(v2app, email='secret-person@example.test')
    text = BODY + '\n\n이 문장도 전송하지 않는다.\n이름: 가상학생\n연락처는 secret-person@example.test입니다.\n010-1234-5678\n\n이 문단은 직접 제외한다.'
    writing = essay(client, headers, text)
    path = freeze(client, headers, writing)
    request, preview = reviewed(client, headers, path, ['p4'])
    assert preview['omittedParagraphIds'] == ['p3'], preview
    assert [x['id'] for x in preview['paragraphs']] == ['p1', 'p2']
    consent(client, headers)
    mismatch = client.post(path + '/ai', headers=headers, json={**request, 'excludeParagraphIds': []})
    assert mismatch.status_code == 409 and gateway.requests == []
    started = client.post(path + '/ai', headers=headers, json=request)
    result = await_run(client, path, started.json['data']['id'])
    assert result['status'] == 'COMPLETED'
    sent = json.loads(gateway.requests[0][0]['messages'][1]['content'])
    assert sent == {'paragraphs': preview['paragraphs']}
    protected_body = BODY + ' 별도 보호 원문.'
    protected = essay(client, headers, protected_body)
    from app.models import SourceDocument, DocumentRevision, EssayDocument
    with v2app.app_context():
        document = SourceDocument(workspace_id='local-workspace', owner_id=uid, scope='PRIVATE', document_type='TEXT',
            title='synthetic protected', original_name='synthetic', stored_name='unique.txt', mime_type='text/plain',
            size=1, access_mode='MATCH_ONLY', rights_confirmed=True)
        db.session.add(document); db.session.flush()
        edition = DocumentRevision(document_id=document.id, revision_number=1, content='별도 보호 원문.', content_hash='a' * 64)
        db.session.add(edition); db.session.flush()
        db.session.add(EssayDocument(writing_id=protected['id'], revision_id=edition.id)); db.session.commit()
    protected_path = freeze(client, headers, protected)
    with v2app.app_context():
        EssayDocument.query.filter_by(writing_id=protected['id']).delete(); db.session.commit()
    denied = client.post(protected_path + '/preview', headers=headers, json={'excludeParagraphIds': []})
    assert denied.status_code == 403 and denied.json['error']['code'] == 'AI_PROTECTED_SOURCE'
    assert len(gateway.requests) == 1


def test_duplicate_revoke_during_call_timeout_and_budget(v2app, gateway, caplog):
    client, headers, _ = user_client(v2app)
    path = freeze(client, headers, essay(client, headers))
    consent(client, headers)
    v2app.config['AI_LIMITS']['monthlyBudgetUnits'] = 6
    data, _ = reviewed(client, headers, path)
    gateway.release.clear()
    started = client.post(path + '/ai', headers=headers, json=data).json['data']
    assert gateway.entered.wait(3)
    duplicate = client.post(path + '/ai', headers=headers, json=data)
    assert duplicate.status_code == 202 and duplicate.json['data']['id'] == started['id']
    consent(client, headers, False)
    assert client.post(path + '/ai', headers=headers, json=data).status_code == 403
    gateway.release.set()
    ended = await_run(client, path, started['id'])
    assert ended['status'] == 'FAILED' and ended['errorCode'] == 'AI_CONSENT_REQUIRED' and not ended['result']
    consent(client, headers)
    gateway.failure = TimeoutError('synthetic-secret-not-for-logs ' + BODY)
    retry = client.post(path + '/ai', headers=headers, json=data)
    assert retry.status_code == 202
    assert await_run(client, path, retry.json['data']['id'])['errorCode'] == 'AI_TIMEOUT'
    other, oh, _ = user_client(v2app, 'limit-other')
    other_path = freeze(other, oh, essay(other, oh))
    consent(other, oh)
    other_data, _ = reviewed(other, oh, other_path)
    blocked = other.post(other_path + '/ai', headers=oh, json=other_data)
    assert blocked.status_code == 429 and blocked.json['error']['code'] == 'AI_BUDGET_LIMIT'
    assert len(gateway.requests) == 2 and BODY not in caplog.text and 'synthetic-secret-not-for-logs' not in caplog.text


def test_selected_questions_and_structure_share_ten_monthly_requests_per_account(v2app, gateway):
    from app.v2.ai_api import reserve_budget

    v2app.config.update(AI_STRUCTURE_POLICY_NOTICE='Synthetic paragraph transfer notice',
        AI_LIMITS={'dailyRequests': 10, 'monthlyRequests': 10, 'callCostUnits': 1,
                   'cooldownSeconds': 0, 'concurrency': 1})
    client, headers, uid = user_client(v2app)
    path = freeze(client, headers, essay(client, headers))
    consent(client, headers)
    with v2app.app_context():
        for _ in range(9):
            assert reserve_budget(uid)
    request, preview = reviewed(client, headers, path)
    assert preview['policyNotice'] == 'Synthetic paragraph transfer notice'
    started = client.post(path + '/ai', headers=headers, json=request)
    assert started.status_code == 202
    assert await_run(client, path, started.json['data']['id'])['status'] == 'COMPLETED'
    _, _, other_id = user_client(v2app, 'other-account-budget')
    with v2app.app_context():
        assert not reserve_budget(uid)
        assert reserve_budget(other_id)
    assert len(gateway.requests) == 1


def test_partial_occurrence_many_to_one_role_difference_and_relation_type():
    body = '반복 반복은 주장이다. 같은 문장. 같은 문장. 마지막.'
    mapping, _ = structure_map(body)
    sentences = mapping['sentences']
    raw = {'nodes': [node('c', 'CLAIM', ('s1', '반복', 2)), node('e', 'EVIDENCE', ('s2', '', 1), ('s3', '', 1)),
        node('last', 'EVIDENCE', ('s4', '', 1))], 'relations': [{'sourceId': 'e', 'targetId': 'c', 'type': 'QUALIFIES', 'basis': 'EXPLICIT'}]}
    ai = validate_ai(raw, body, sentences, {'s1', 's2', 's3', 's4'})
    assert ai['nodes'][0]['spans'][0]['start'] == 3
    left = [ai['nodes'][0], *[{**ai['nodes'][1], 'id': f'e{i}', 'spans': [span]} for i, span in enumerate(ai['nodes'][1]['spans'])],
            {**ai['nodes'][2], 'id': 'd', 'role': 'CLAIM'}]
    relation = {**ai['relations'][0], 'sourceId': 'e1', 'type': 'SUPPORTS'}
    comparison = compare_structures({'nodes': left, 'relations': [relation]}, ai)
    assert [x['status'] for x in comparison['nodes']] == ['SAME_SPAN_ROLE', 'SAME_ROLE_DIFFERENT_SPAN', 'SAME_SPAN_DIFFERENT_ROLE']
    assert len(comparison['relations']) == 2
    relation['type'] = 'QUALIFIES'
    assert not compare_structures({'nodes': left, 'relations': [relation]}, ai)['relations']
    relation['direction'] = 'CLAIM_TO_EVIDENCE'
    assert len(compare_structures({'nodes': left, 'relations': [relation]}, ai)['relations']) == 2


def test_paragraph_result_does_not_fill_missing_or_excluded_roles():
    mapping, quotes = structure_map(BODY)
    empty = {'nodes': [], 'relations': [], 'quotations': []}
    result = validate_paragraph_ai(empty, BODY, mapping, quotes, {'p1'})
    assert result['paragraphs'] == [{'paragraphId': 'p1', 'claimCount': 0, 'evidenceCount': 0, 'quotationCount': 0}]
    with pytest.raises(ValueError, match='AI_PARAGRAPH_INVALID'):
        validate_paragraph_ai({**empty, 'quotations': response()['quotations']}, BODY, mapping, quotes, {'p1'})


def test_structure_request_byte_limit_blocks_preview_and_transport_without_spending(v2app, gateway):
    from dataclasses import replace
    from app.v2.baze_provider import ProviderUnavailable

    structure_provider = v2app.extensions['structure_provider']
    structure_provider.settings = replace(structure_provider.settings, max_request_bytes=4096)
    text = '가' * 1500
    client, headers, _ = user_client(v2app)
    path = freeze(client, headers, essay(client, headers, text))
    preview = client.post(path + '/preview', headers=headers, json={'excludeParagraphIds': []})
    assert preview.status_code == 413 and preview.json['error']['code'] == 'AI_INPUT_LIMIT'
    with pytest.raises(ProviderUnavailable, match='AI_INPUT_LIMIT'):
        structure_provider.structure([{'id': 'p1', 'text': text}])
    assert gateway.requests == []


def test_payload_cap_default_off_and_sqlite_lock_stay_optional(v2app, gateway):
    import sqlite3
    from sqlalchemy import event
    client, headers, _ = user_client(v2app)
    writing = essay(client, headers)
    path = freeze(client, headers, writing)
    oversized = client.post(path + '/preview', headers=headers, json={'excludeParagraphIds': ['x' * 17000]})
    assert oversized.status_code == 413
    v2app.config['AI_STRUCTURE_ENABLED'] = False
    assert client.post(path + '/preview', headers=headers, json={'excludeParagraphIds': []}).status_code == 503
    v2app.config['AI_STRUCTURE_ENABLED'] = True
    consent(client, headers)
    data, _ = reviewed(client, headers, path)
    with v2app.app_context():
        @event.listens_for(db.engine, 'checkout')
        def short_timeout(connection, _record, _proxy):
            connection.execute('PRAGMA busy_timeout=100')
    with sqlite3.connect(v2app.config['DATABASE_PATH']) as lock:
        lock.execute('BEGIN IMMEDIATE')
        busy = client.post(path + '/ai', headers=headers, json=data)
        assert busy.status_code == 429 and busy.json['error']['code'] == 'AI_BUSY'
        assert client.get('/api/writings/' + writing['id']).status_code == 200
    assert not gateway.requests
    started = client.post(path + '/ai', headers=headers, json=data)
    assert started.status_code == 202
    assert await_run(client, path, started.json['data']['id'])['status'] == 'COMPLETED'


def test_isolated_restore_preserves_ledger_and_requires_fresh_structure_consent(v2app, gateway, tmp_path):
    import sqlite3
    from contextlib import closing
    from app.services import backup_service as backup
    client, headers, _ = user_client(v2app)
    path = freeze(client, headers, essay(client, headers))
    consent(client, headers)
    data, _ = reviewed(client, headers, path)
    started = client.post(path + '/ai', headers=headers, json=data)
    assert started.status_code == 202
    assert await_run(client, path, started.json['data']['id'])['status'] == 'COMPLETED'
    key = b'a' * 32
    with v2app.app_context():
        archive = backup.build_bundle(key, quiescent=True)
    consent(client, headers, False)
    with v2app.app_context():
        budget = db.session.get(AppSetting, 'ai_monthly_usage')
        budget.value = {**budget.value, 'spent': 6}
        db.session.commit()
        destination = tmp_path / 'dual-restored'
        receipt = backup.restore_bundle(archive, key, destination, v2app.config['DATABASE_PATH'])
    assert receipt['quarantined'] and receipt['revision'] == '0006_dual_structure'
    with closing(sqlite3.connect(destination / 'db/geulbit.sqlite3')) as restored:
        assert restored.execute("SELECT count(*) FROM consents WHERE kind='AI_STRUCTURE' AND revoked_at IS NULL").fetchone() == (0,)
        assert json.loads(restored.execute("SELECT value FROM app_settings WHERE key='ai_monthly_usage'").fetchone()[0])['spent'] == 6
        assert restored.execute('SELECT status FROM essay_structure_runs').fetchone() == ('COMPLETED',)
        assert not restored.execute('PRAGMA foreign_key_check').fetchall()
