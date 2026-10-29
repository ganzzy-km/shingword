import sys
from pathlib import Path
import unicodedata
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'app'))
from analysis.reviewed_norms import REVIEWED_PAIRS, rule_id, provision_links
from analysis.ruleset import catalogue, local_findings, ruleset_hash
from analysis.norms_catalogue import provision_reference, catalogue_manifest
from analysis.structure import analyze_structure


@pytest.mark.parametrize('index,case', list(enumerate(REVIEWED_PAIRS)))
def test_every_new_candidate_normal_quote_vocabulary_disable_and_unicode_span(index, case):
    article, page, bad, good = case
    identifier = rule_id(index)
    body = unicodedata.normalize('NFC', '😀 '+bad+'\n'+good+'.')
    findings = [f for f in local_findings(body) if f['ruleId'] == identifier]
    assert len(findings) == 1
    finding = findings[0]
    assert body[finding['start']:finding['end']] == bad
    assert finding['suggestion'] == (None if bad=='번번히' else good)
    assert finding['tier'] == ('표현 제안' if bad=='번번히' else '확인 필요') and finding['autoApply'] is False
    assert finding['source']['primaryReference']['location']['pdfPages'] == [page]
    assert f'SPELLING-{article:03d}' in finding['source']['primaryReference']['provisionIds']
    assert local_findings('“'+bad+'”') == []
    assert not any(f['ruleId'] == identifier for f in local_findings(bad, vocabulary=[bad]))
    assert not any(f['ruleId'] == identifier for f in local_findings(bad, disabled=[identifier]))
    assert not any(f['ruleId'] == identifier for f in local_findings(good))
    assert local_findings('새'+bad+'이름') == []


@pytest.mark.parametrize('normal', ['돼요','되어요','되고','되면','되지','돼지','뵈면','봬요','뵈어요',
    '그렇지 않다','그렇잖다','만만하지 않다','만만찮다','장군','일군 부대','일군 성과',
    '금새가 비싸다','금세 끝났다','왔다','보아라','봐라','좋아','놔','놓아',
    '깨끗이','따뜻이','번듯이','솔직히','조용히','굉장히','열심히',
    '갈까','갈꼬','갈쏘냐','10개','한 개','삼학년','삼 학년','꺼져간다','꺼져 간다'])
def test_permitted_forms_and_semantic_homographs_are_not_blanket_corrected(normal):
    assert local_findings(normal) == []


def test_all_new_links_detached_complete_source_and_hash_deterministic():
    assert len(catalogue()) == 39 and ruleset_hash() == ruleset_hash()
    for provision, ids in provision_links().items():
        record = provision_reference(provision)
        assert set(ids) <= set(record['detectorRuleIds'])
        assert record['passages'] and record['exception']['mustPreserveFullProvision']
        assert record['execution'] == 'BOUNDED_CANDIDATES'
    meta = catalogue_manifest()
    assert meta['linkedProvisions'] == 11 and meta['referenceOnlyProvisions'] == 123


@pytest.mark.parametrize('body', ['잊어버리기 쉽상이다.', '넘어지기 쉽상입니다.', '쉽상', '😀 쉽상이지만 십상이다.'])
def test_sipsang_lexical_candidate_and_exact_span(body):
    findings=[f for f in local_findings(body) if f['ruleId']=='gb-lexical-001']
    assert len(findings)==1
    f=findings[0]
    assert body[f['start']:f['end']]=='쉽상' and f['suggestion']=='십상'
    assert 'mcfaq_seq=5661' in f['source']['url']
    assert not any(f['ruleId']=='gb-lexical-001' for f in local_findings(body,disabled=['gb-lexical-001']))


def test_gomgom_allowed_forms_sipsang_quote_and_vocabulary_exceptions():
    assert local_findings('곰곰 생각한다. 곰곰이 생각한다. 잊기 십상이다.')==[]
    findings=local_findings('잊어버리기 쉽상이다. 곰곰히 생각해 본다.')
    assert [(f['quote'],f['suggestion']) for f in findings]==[('쉽상','십상'),('곰곰히','곰곰이')]
    assert local_findings('“쉽상이다”라고 썼다. “곰곰히”라는 인용.')==[]
    assert local_findings('쉽상이다.',vocabulary=['쉽상'])==[]
    assert local_findings('쉽상리라는 지명 새쉽상이다.')==[]


def test_real_engine_short_essay_new_rules_determinism_and_snapshot_provenance():
    normal = '나는 할 수 있다. 며칠 동안 책을 읽었다. 잘 되어야 한다. 오늘은 돼요. 깨끗이 정리하고 할게. 심부름꾼이 팔꿈치를 다쳤다. 😀'
    mixed = '나는 할수 있다. 몇일 동안 읽었다. 오늘은 되요. 깨끗히 정리하고 할께. 심부름군이 팔굼치를 다쳤다. “되요”는 직접 인용이다. 😀'
    assert local_findings(normal) == []
    first = analyze_structure(mixed, version_id='synthetic-reviewed-v1')
    again = analyze_structure(mixed, version_id='synthetic-reviewed-v1')
    assert first == again
    hits = [f for f in first['findings'] if f.get('ruleId')]
    assert len(hits) == 7
    assert any(f['quote'] == '되요' for f in hits)
    for finding in hits:
        assert mixed[finding['start']:finding['end']] == finding['quote']
        assert finding['autoApply'] is False
