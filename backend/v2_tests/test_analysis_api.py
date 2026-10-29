from v2_fixture import v2app,user_client
from app.extensions import db
from app.models import Analysis,WritingVersion
from app.v2 import analysis_api


def essay(client,headers,body='나는 의미가 있다고 생각한다.\n\n작품에서 인물은 달렸다. 😀'):
    return client.post('/api/writings',headers=headers,json={'title':'synthetic','content':body,'inquiryQuestion':'synthetic question'}).json['data']


def analyze(app,client,headers,w,body=None):
    app.config['ANALYSIS_SYNCHRONOUS']=True
    return client.post('/api/analyses',headers=headers,json={'writingId':w['id'],'content':w['content'] if body is None else body,'revisionNumber':w['revisionNumber']})


def test_actual_kiwi_run_version_schema_and_spans(v2app):
    c,h,_=user_client(v2app);w=essay(c,h);r=analyze(v2app,c,h,w)
    assert r.status_code==202;ids=r.json['data']
    assert c.get('/api/analysis-jobs/'+ids['jobId']).json['data']['status']=='completed'
    result=c.get('/api/analyses/'+ids['analysisId']).json['data']
    assert result['sourceVersion']['content']==w['content'] and result['result']['input']['versionId']==ids['essayVersionId']
    assert result['result']['manifest']['analyzer']=='kiwi'
    for s in result['sentences']:assert w['content'][s['startOffset']:s['endOffset']]==s['text']
    with v2app.app_context():
        run=db.session.get(Analysis,ids['analysisId']);assert 'content' not in run.result_snapshot['input'];assert run.essay_version_id==ids['essayVersionId']


def test_missing_body_or_revision_conflict(v2app):
    c,h,_=user_client(v2app);w=essay(c,h)
    assert c.post('/api/analyses',headers=h,json={'writingId':w['id']}).status_code==400
    w['revisionNumber']=0;assert analyze(v2app,c,h,w).status_code==409
    with v2app.app_context():assert Analysis.query.count()==0


def test_edit_during_analysis_keeps_fixed_version_without_write_lock(v2app,monkeypatch):
    import sqlite3
    c,h,_=user_client(v2app);w=essay(c,h);real=analysis_api.analyze_input
    def edit(body,vid,context):
        with sqlite3.connect(v2app.config['DATABASE_PATH'],timeout=.1) as external:
            external.execute('BEGIN IMMEDIATE');external.rollback()
        response=c.post('/api/writings/'+w['id']+'/autosave',headers=h,json={'content':'new synthetic edit 😀','revisionNumber':1})
        assert response.status_code==200
        return real(body,vid,context)
    monkeypatch.setattr(analysis_api,'analyze_input',edit)
    r=analyze(v2app,c,h,w);result=c.get('/api/analyses/'+r.json['data']['analysisId']).json['data']
    assert result['status']=='completed' and result['sourceVersion']['content']==w['content']
    assert c.get('/api/writings/'+w['id']).json['data']['content']=='new synthetic edit 😀'


def test_failed_run_preserves_previous_success(v2app,monkeypatch):
    c,h,_=user_client(v2app);w=essay(c,h);first=analyze(v2app,c,h,w).json['data']
    def fail(*_a):raise RuntimeError('synthetic analysis failure')
    monkeypatch.setattr(analysis_api,'analyze_input',fail)
    second=analyze(v2app,c,h,w).json['data']
    assert c.get('/api/analysis-jobs/'+second['jobId']).json['data']['status']=='failed'
    assert c.get('/api/writings/'+w['id']).json['data']['latestAnalysisId']==first['analysisId']
    assert c.get('/api/analyses/'+first['analysisId']).json['data']['status']=='completed'


def test_other_user_and_admin_cannot_read_run_or_job(v2app):
    c,h,_=user_client(v2app);w=essay(c,h);ids=analyze(v2app,c,h,w).json['data']
    for subject,role in [('synthetic-other','USER'),('synthetic-admin','ADMIN')]:
        other,oh,_=user_client(v2app,subject,role)
        assert other.get('/api/analyses/'+ids['analysisId']).status_code==404
        assert other.get('/api/analysis-jobs/'+ids['jobId']).status_code==404


def test_timeout_and_completed_cancel_refused(v2app):
    c,h,_=user_client(v2app);w=essay(c,h);first=analyze(v2app,c,h,w).json['data']
    assert c.post('/api/analysis-jobs/'+first['jobId']+'/cancel',headers=h).status_code==409
    v2app.config['ANALYSIS_TIMEOUT_SECONDS']=0
    second=analyze(v2app,c,h,w).json['data']
    result=c.get('/api/analysis-jobs/'+second['jobId']).json['data']
    assert result['status']=='failed' and '시간' in result['errorMessage']
