from pathlib import Path
from v2_fixture import v2app, user_client
from app.analysis.ruleset import catalogue, local_findings, RULESET_VERSION


def test_display_examples_are_detector_examples_not_regex(v2app):
    client, _, _ = user_client(v2app)
    rows = client.get('/api/rules').json['data']
    assert len(rows) == len(catalogue()) == 39 and len({r['id'] for r in rows}) == 39
    assert any(r['id']=='gb-lexical-001' for r in rows)
    for row, rule in zip(rows, catalogue()):
        assert row['name'] not in {'spacing', 'spelling', 'typo', 'context'}
        assert row['incorrectExamples'] == rule['positive_examples']
        assert row['correctExamples'] == rule['negative_examples']
        assert row['exceptionExamples'] == rule['exception_examples']
        for text in row['incorrectExamples']:
            assert any(f['ruleId'] == row['id'] for f in local_findings(text))
        for text in row['correctExamples']:
            assert not any(f['ruleId'] == row['id'] for f in local_findings(text))
    assert rows[0]['incorrectExamples'] == ['할수 있다']
    assert rows[0]['correctExamples'] == ['할 수 있다']


def test_primary_pdf_provenance_and_missing_dates_are_not_fabricated(v2app):
    client, _, _ = user_client(v2app)
    rows = client.get('/api/rules').json['data']
    primary = rows[0]['primaryReference']
    assert primary['reference']['pdfPageCount'] == 314
    assert primary['normsCatalogue']['provisionCount'] == 134
    assert primary['normsCatalogue']['referenceRole'] == 'PRIMARY_NORMATIVE_BASIS'
    assert primary['location']['pdfPages'] == [26, 151]
    assert primary['reference']['currentNormsChecked'] is False
    assert rows[2]['primaryReference'] is None
    assert rows[2]['source']['checkedAt'] is None
    assert '출처 대조' in rows[2]['source']['name']


def test_rules_ui_does_not_render_internal_pattern_or_null_date():
    source = (Path(__file__).resolve().parents[2] / 'src' / 'App.tsx').read_text(encoding='utf-8')
    screen = source.split('function RulesScreen()', 1)[1].split('// ─── Settings', 1)[0]
    assert '{r.pattern}' not in screen and '{r.replacement' not in screen
    assert 'if (!value) return "확인일 미등록"' in screen
    assert 'key={rule.id}' in screen
    assert 'r.incorrectExamples' in screen and 'r.correctExamples' in screen


def test_rules_api_keeps_authentication(v2app):
    assert v2app.test_client().get('/api/rules').status_code == 401
    assert v2app.test_client().get('/api/rules/reference').status_code == 401
    assert v2app.test_client().get('/api/rules/reference/SPELLING-042').status_code == 401


def test_all_reference_entries_and_details_are_available_without_fabricated_detection(v2app):
    client, _, _ = user_client(v2app)
    index = client.get('/api/rules/reference').json['data']
    assert index['manifest']['provisionCount'] == 134
    for entry in index['provisions']:
        response = client.get('/api/rules/reference/'+entry['id'])
        assert response.status_code == 200
        record = response.json['data']
        assert record['rule_id'] == entry['id'] and record['autoApply'] is False
        assert record['passages'] and all(p['text'] for p in record['passages'])
        assert record['execution'] == ('BOUNDED_CANDIDATES' if entry['detectorRuleIds'] else 'REFERENCE_ONLY')
    assert client.get('/api/rules/reference/UNKNOWN').status_code == 404


def test_normalized_detector_status_and_disable_state(v2app):
    from app.extensions import db
    from app.models import AppSetting
    with v2app.app_context():
        db.session.add(AppSetting(key='disabled_rules', value=['gb-local-001']))
        db.session.commit()
    client, _, _ = user_client(v2app)
    rows = client.get('/api/rules').json['data']
    assert rows[0]['active'] is False and rows[0]['status'] == '비활성'
    for row, rule in zip(rows, catalogue()):
        assert row['name'] == rule['title'] and row['scope'] == rule['scope']
        assert row['version'] == RULESET_VERSION
        assert row['categoryLabel'] == rule['categoryLabel']
