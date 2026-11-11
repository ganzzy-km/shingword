"""Explicitly reviewed lexical candidates; never derive error columns from PDF text.

Source pages were visually inspected against the supplied immutable PDF.
The complete provision, permissions and exceptions remain in norms_catalogue.
These bounded candidates do not implement an entire article or auto-correct text.
"""
import re

OFFICIAL_NORMS_URL = 'https://www.korean.go.kr/kornorms/m/m_regltn.do'
REVIEWED_PAIRS = [
    (9, 76, '띠어쓰기', '띄어쓰기'), (9, 76, '히망', '희망'),
    (25, 122, '더우기', '더욱이'), (25, 122, '일찌기', '일찍이'), (25, 122, '곰곰히', '곰곰이'),
    (35, 141, '되요', '돼요'), (35, 141, '됬다', '됐다'), (35, 141, '됬어요', '됐어요'),
    (35, 141, '됬습니다', '됐습니다'), (35, 141, '뵈요', '봬요'),
    (39, 145, '그렇쟎다', '그렇잖다'), (39, 145, '만만챦다', '만만찮다'),
    (51, 170, '깨끗히', '깨끗이'), (51, 170, '일일히', '일일이'), (51, 170, '틈틈히', '틈틈이'),
    (51, 170, '겹겹히', '겹겹이'), (51, 170, '번번히', '번번이'),
    (53, 175, '할께', '할게'), (53, 175, '갈께', '갈게'), (53, 175, '볼께', '볼게'),
    (53, 175, '먹을께', '먹을게'),
    (54, 175, '심부름군', '심부름꾼'), (54, 175, '익살군', '익살꾼'), (54, 175, '장난군', '장난꾼'),
    (54, 175, '뒷굼치', '뒤꿈치'), (54, 175, '팔굼치', '팔꿈치'), (54, 175, '빛갈', '빛깔'),
    (54, 175, '땟갈', '때깔'), (55, 177, '마추다', '맞추다'), (55, 177, '뻐치다', '뻗치다'),
]

# A bounded lexical suffix list avoids matching within arbitrary proper names.
# Unlisted inflections intentionally receive no finding rather than a guess.
WORD_CHARS = '가-힣A-Za-z0-9_'
SUFFIXES = r'(?:에서|으로|에게|이라도|이라고|라고|라는|은|는|이|가|을|를|의|도|만|에|요)'


def rule_id(index):
    return f'gb-norm-{index + 1:03d}'


def pattern_for(word):
    return rf'(?<![{WORD_CHARS}]){re.escape(word)}(?=$|[^{WORD_CHARS}]|{SUFFIXES}(?=$|[^{WORD_CHARS}]))'


def provision_links():
    links = {}
    for index, (article, _page, _bad, _good) in enumerate(REVIEWED_PAIRS):
        links.setdefault(f'SPELLING-{article:03d}', []).append(rule_id(index))
    return links


def reviewed_records(version, reference_lookup):
    records = []
    for index, (article, page, bad, good) in enumerate(REVIEWED_PAIRS):
        identifier = rule_id(index)
        url = ('https://korean.go.kr/front/mcfaq/mcfaqView.do?mcfaq_seq=6761&mn_id=62&pageIndex=5'
               if bad == '되요' else OFFICIAL_NORMS_URL)
        source = {'legacyCaption': f'한글 맞춤법 제{article}항', 'url': url, 'verifiedAt': '2026-10-11',
                  'status': 'PDF_TABLE_VISUALLY_REVIEWED', 'reviewedPdfPages': [page],
                  'primaryReference': reference_lookup(identifier)}
        records.append({'rule_id': identifier, 'version': version, 'category': 'spelling',
            'title': f'{bad} → {good}', 'categoryLabel': '맞춤법', 'scope': f'검증한 {bad} 표현과 제한된 조사·요 결합만 검사합니다. 같은 조항의 다른 표현은 자동 판정하지 않습니다.',
            'execution': 'BOUNDED_CANDIDATES', 'autoApply': False, 'tier': '확인 필요',
            'condition': pattern_for(bad), 'suggestion': good,
            'exception': '직접 인용, 등록된 고유 어휘 및 다른 낱말 내부 일치는 보호합니다.',
            'reason': f'해당 문맥에서 {good}로 적는지 확인해 주세요. 제공 규범집 제{article}항의 표기·허용 조건을 근거로 한 제한적 후보입니다.',
            'source': source, 'positive_examples': [bad], 'negative_examples': [good],
            'exception_examples': [bad+'라는 작품 이름'], 'known_false_positives': ['등록되지 않은 고유명사·의도적 옛 표기'],
            'examples': {'candidate': [bad], 'normal': [good], 'exception': [bad+'라는 작품 이름'], 'exceptionVocabulary': [bad]}})
        record=records[-1]
        record['selectionPolicy']='STANDARD_SPELLING'
        if bad=='곰곰히':
            record['title']='곰곰·곰곰이: 표준 표기 제안'
            record['reason']="여러모로 깊이 생각하는 뜻에는 '곰곰'과 '곰곰이'를 모두 쓸 수 있습니다. '곰곰히'는 문맥에 따라 쓰는 별도 표준형이 아닙니다. '곰곰이 생각하다' 또는 '곰곰 생각하다'를 선택해 보세요. 정상 표현끼리는 바꾸도록 요구하지 않습니다."
            record['alternatives']=[{'text':'곰곰이','when':'여러모로 깊이 생각하는 모양','example':'곰곰이 생각해 보았다.'},{'text':'곰곰','when':'같은 뜻의 허용 표현','example':'곰곰 생각해 보았다.'}]
            record['source'].update(url='https://www.korean.go.kr/front/onlineQna/onlineQnaView.do?mn_id=216&qna_seq=305970',verifiedAt='2026-10-12',status='PRIMARY_SOURCE_CHECKED')
        if bad=='번번히':
            # Similar spellings cannot be treated as a universal replacement.
            # The PDF supplies a spelling example, not an intent classifier.
            record.update(category='context',categoryLabel='문맥 구별',tier='표현 제안',
                title='번번이·번번히: 뜻을 먼저 확인',suggestion=None,selectionPolicy='CONTEXT_REQUIRED',
                scope='번번히를 오류로 단정하지 않고 뜻에 맞는 표기를 확인하도록 안내합니다.',
                reason="매번·매 때마다라는 뜻을 의도했다면 '번번이'를 검토해 보세요. 다른 뜻이나 작품 고유 표현이라면 문맥과 사전의 뜻풀이를 먼저 확인하세요. 표기가 비슷하다는 이유로 '번번히'를 일괄 교체하지 않습니다.")
    return records


def lexical_records(version):
    # Separate dictionary evidence from visually reviewed PDF tables. Do not
    # invent a PDF article/page for a word that is absent from those tables.
    return [{'rule_id': 'gb-lexical-001', 'version': version, 'category': 'spelling',
        'title': '쉽상 → 십상', 'categoryLabel': '맞춤법',
        'scope': '쉽상 및 제한된 서술격 조사 결합을 검사합니다.',
        'execution': 'BOUNDED_CANDIDATES', 'autoApply': False, 'tier': '오류 후보',
        'condition': rf'(?<![{WORD_CHARS}])쉽상(?=$|[^{WORD_CHARS}]|(?:이다|입니다|이었다|이었고|이고|이라|이라서|이라고|이므로|이지만|인|일|이에요|이죠)(?=$|[^{WORD_CHARS}]))',
        'suggestion': '십상', 'exception': '직접 인용, 등록된 고유 어휘 및 낱말 내부 일치를 보호합니다.',
        'reason': "거의 예외 없이 그렇게 되기 쉬움을 나타내는 말은 '십상'으로 적습니다. 뒤의 '이다' 등은 그대로 유지하세요.",
        'source': {'legacyCaption': "국립국어원: '쉽상'과 '십상'의 표현",
            'url': 'https://www.korean.go.kr/front/mcfaq/mcfaqView.do?mcfaq_seq=5661&mn_id=62&pageIndex=246',
            'verifiedAt': '2026-10-12', 'status': 'PRIMARY_SOURCE_CHECKED', 'primaryReference': None},
        'positive_examples': ['쉽상이다', '쉽상입니다', '쉽상'],
        'negative_examples': ['십상이다', '십상입니다', '곰곰 생각한다', '곰곰이 생각한다'],
        'exception_examples': ['쉽상이라는 인물'], 'known_false_positives': ['등록되지 않은 고유명사'],
        'examples': {'candidate': ['쉽상이다', '쉽상입니다', '쉽상'], 'normal': ['십상이다', '십상입니다', '곰곰 생각한다', '곰곰이 생각한다'],
            'exception': ['쉽상이라는 인물'], 'exceptionVocabulary': ['쉽상']}}]
