"""Explicit retirement contract for NEW standard jobs, old data still readable."""
import pytest
from test_ocr_api import setup,ready
from v2_fixture import v2app
from app.models import OcrRun,SourceDocument,DocumentRevision
from app.extensions import db
from app.services import ocr_jobs as jobs

def test_retired_upload_creates_no_file_document_revision_or_job(setup):
    app,c,h,owner,did,jid,doc,upload=setup
    from pathlib import Path
    with app.app_context():
        before=(SourceDocument.query.count(),DocumentRevision.query.count(),OcrRun.query.count())
        folder=Path(app.config['UPLOAD_FOLDER']);files={p.name for p in folder.iterdir()}
    response=upload(ocrMode='standard');assert response.status_code==400 and response.json['error']['code']=='OCR_MODE_RETIRED'
    with app.app_context():
        assert before==(SourceDocument.query.count(),DocumentRevision.query.count(),OcrRun.query.count())
        assert files=={p.name for p in folder.iterdir()}

def test_retired_restart_never_creates_a_job_or_mutates_current_revision(setup):
    app,c,h,owner,did,jid,doc,_=setup
    response=c.post('/api/source-documents/'+did+'/ocr',headers=h,json={'expectedRevisionId':doc['latestRevisionId'],'ocrMode':'standard'})
    assert response.status_code==400 and response.json['error']['code']=='OCR_MODE_RETIRED'
    with app.app_context():assert OcrRun.query.count()==1 and DocumentRevision.query.filter_by(document_id=did).count()==1

def test_service_cannot_create_a_new_standard_document_job(setup):
    app,c,h,owner,did,jid,doc,_=setup
    with app.app_context():
        item=db.session.get(SourceDocument,did)
        with pytest.raises(ValueError,match='OCR_MODE_RETIRED'):jobs.create_job(item,doc['latestRevisionId'],mode='standard')
        assert OcrRun.query.count()==1

def test_historical_standard_draft_read_confirm_and_export_stay_available(setup):
    app,c,h,owner,did,jid,doc,_=setup;ready(app,jid,'기존 일반 OCR 검수 원문')
    with app.app_context():
        _,meta=jobs.row(jid);meta.value={**meta.value,'ocrMode':'standard'};db.session.commit()
    old=c.get('/api/ocr-jobs/'+jid);assert old.status_code==200 and old.json['data']['ocrMode']=='standard'
    confirmed=c.post('/api/ocr-jobs/'+jid+'/confirm',headers=h,json={'expectedDraftVersion':1,'expectedRevisionId':doc['latestRevisionId']})
    assert confirmed.status_code==201 and confirmed.json['data']['revisionId']!=doc['latestRevisionId']
    source=c.get('/api/source-documents/'+did);assert source.json['data']['content']=='기존 일반 OCR 검수 원문'
    assert c.get('/api/ocr-jobs/'+jid).json['data']['status']=='CONFIRMED'
    exported=c.get('/api/ocr-jobs/'+jid+'/export/json');assert exported.status_code==200
    assert exported.json['text']=='기존 일반 OCR 검수 원문' and exported.json['ocrMode']=='standard'

@pytest.mark.parametrize('profile',['auto','poetry','prose','drama','commentary','other'])
def test_default_new_upload_is_precise_with_user_profile(setup,profile):
    app,c,h,owner,did,jid,doc,upload=setup
    r=upload(ocrProfile=profile);assert r.status_code==201
    job=c.get('/api/ocr-jobs/'+r.json['data']['ocr']['jobId']).json['data'];assert job['ocrMode']=='precise' and job['ocrProfile']==profile
