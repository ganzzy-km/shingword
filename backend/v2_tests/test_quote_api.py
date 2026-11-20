from v2_fixture import v2app,user_client
from test_library_api import upload
from test_analysis_api import essay,analyze


def test_exact_normalized_and_unrelated_selected_revision(v2app):
    c,h,_=user_client(v2app);response=upload(c,h,'그는 조용히 문을 열었다. 😀');d=response.json['data']
    def search(q):return c.post('/api/source-documents/'+d['id']+'/search',headers=h,json={'revisionId':d['latestRevisionId'],'quote':q}).json['data']
    assert search('조용히 문을 열었다')['status']=='EXACT_MATCH'
    assert search('조용히문을열었다')['status']=='NORMALIZED_MATCH'
    absent=search('관련없는다른판본구절');assert absent['status']=='NOT_FOUND_IN_SELECTED_REVISION' and '옳고 그름을 확정하지' in absent['limitation']


def test_edition_revision_changes_without_rebinding(v2app):
    c,h,_=user_client(v2app);d=upload(c,h,'old synthetic edition').json['data'];old=d['latestRevisionId']
    new=c.post('/api/source-documents/'+d['id']+'/revisions',headers=h,json={'content':'new synthetic edition','expectedRevisionId':old}).json['data']['id']
    def search(rid):return c.post('/api/source-documents/'+d['id']+'/search',headers=h,json={'revisionId':rid,'quote':'old synthetic edition'}).json['data']
    assert search(old)['status']=='EXACT_MATCH' and search(new)['status']!='EXACT_MATCH'
    other=upload(c,h,'other source').json['data']
    assert c.post('/api/source-documents/'+d['id']+'/search',headers=h,json={'revisionId':other['latestRevisionId'],'quote':'other source'}).status_code==404


def test_match_only_no_excerpt_and_idor(v2app):
    c,h,_=user_client(v2app);d=upload(c,h,'그는 문을 열었다.',accessMode='MATCH_ONLY').json['data']
    result=c.post('/api/source-documents/'+d['id']+'/search',headers=h,json={'revisionId':d['latestRevisionId'],'quote':'문을 열었다'}).json['data']
    assert result['status']=='EXACT_MATCH' and 'excerpt' not in result
    other,oh,_=user_client(v2app,'synthetic-other')
    assert other.post('/api/source-documents/'+d['id']+'/search',headers=oh,json={'revisionId':d['latestRevisionId'],'quote':'문을 열었다'}).status_code==404


def test_analysis_manifest_pins_selected_revision_and_quote_checks(v2app):
    c,h,_=user_client(v2app);d=upload(c,h,'그는 문을 열었다.').json['data'];w=essay(c,h,'나는 “문을 열었다”는 구절을 선택했다.')
    assert c.post('/api/writings/'+w['id']+'/documents',headers=h,json={'revisionId':d['latestRevisionId']}).status_code==200
    ids=analyze(v2app,c,h,w).json['data'];result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert result['contextSnapshot']['documents'][0]['revisionId']==d['latestRevisionId']
    checks=result['result']['quoteChecks'];assert checks and checks[0]['status']=='EXACT_MATCH'
    assert 'excerpt' not in checks[0]

    visible=[f for f in result['findings'] if f['type']=='quotation'];assert visible and visible[0]['current']=='문을 열었다' and visible[0]['metadata']['revisionId']==d['latestRevisionId']
