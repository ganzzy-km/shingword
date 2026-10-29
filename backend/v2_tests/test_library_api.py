import io
from pathlib import Path
import fitz
import pytest
from sqlalchemy.exc import IntegrityError
from v2_fixture import v2app,user_client
from app.extensions import db
from app.models import SourceDocument,DocumentRevision,WorkDocument


def upload(client,headers,body='synthetic source 가😀',**metadata):
    return client.post('/api/source-documents',headers=headers,data={'file':(io.BytesIO(body.encode()),'synthetic.txt'),'title':'synthetic source',**metadata})


def test_private_work_crud_and_foreign_owner(v2app):
    c,h,_=user_client(v2app);other,oh,_=user_client(v2app,'synthetic-other')
    response=c.post('/api/works',headers=h,json={'title':'synthetic work','vocabulary':['인물명']});assert response.status_code==201;wid=response.json['data']['id']
    assert other.get('/api/works').json['data']==[]
    assert other.patch('/api/works/'+wid,headers=oh,json={'title':'stolen'}).status_code==404
    assert c.patch('/api/works/'+wid,headers=h,json={'title':'new title'}).status_code==200
    assert c.delete('/api/works/'+wid,headers=h).status_code==200


def test_private_document_upload_view_and_idor(v2app):
    c,h,_=user_client(v2app);other,oh,_=user_client(v2app,'synthetic-other');r=upload(c,h);assert r.status_code==201;did=r.json['data']['id']
    assert c.get('/api/source-documents/'+did).json['data']['content']=='synthetic source 가😀'
    assert other.get('/api/source-documents').json['data']==[]
    assert other.get('/api/source-documents/'+did).status_code==404
    admin,ah,_=user_client(v2app,'synthetic-admin','ADMIN')
    assert admin.get('/api/source-documents/'+did).status_code==404


def test_public_add_rights_and_delete_permissions_are_separate(v2app):
    admin,ah,_=user_client(v2app,'synthetic-admin','ADMIN')
    assert upload(admin,ah,scope='PUBLIC',rightsConfirmed='true',rightsInfo='synthetic test rights').status_code==403
    writer,wh,_=user_client(v2app,'synthetic-public-writer',email='ps00000@onedu.jje.go.kr',verified=True)
    assert upload(writer,wh,scope='PUBLIC').status_code==403
    response=writer.post('/api/works',headers=wh,json={'title':'synthetic public work','scope':'PUBLIC'});wid=response.json['data']['id']
    assert writer.delete('/api/works/'+wid,headers=wh).status_code==403
    assert admin.delete('/api/works/'+wid,headers=ah).status_code==200


def test_match_only_no_body_or_download_and_private_access_mode(v2app):
    c,h,_=user_client(v2app);r=upload(c,h,accessMode='MATCH_ONLY');did=r.json['data']['id'];rid=r.json['data']['latestRevisionId']
    assert 'content' not in c.get('/api/source-documents/'+did).json['data']
    assert c.get('/api/source-documents/'+did+'/revisions/'+rid).status_code==404
    assert c.get('/api/files/source/'+did).status_code==404
    r=upload(c,h,accessMode='DOWNLOAD');did=r.json['data']['id']
    response=c.get('/api/files/source/'+did);assert response.status_code==200 and response.data.decode()=='synthetic source 가😀'
    assert 'attachment' in response.headers['Content-Disposition']


def test_append_revision_and_stale_revision_conflict(v2app):
    c,h,_=user_client(v2app);r=upload(c,h);did=r.json['data']['id'];rid=r.json['data']['latestRevisionId']
    new=c.post('/api/source-documents/'+did+'/revisions',headers=h,json={'content':'new edition','expectedRevisionId':rid});assert new.status_code==201
    assert c.get('/api/source-documents/'+did+'/revisions/'+rid).json['data']['content']=='synthetic source 가😀'
    assert c.post('/api/source-documents/'+did+'/revisions',headers=h,json={'content':'stale','expectedRevisionId':rid}).status_code==409
    with v2app.app_context():
        revision=db.session.get(DocumentRevision,rid);revision.content='tampered'
        with pytest.raises(IntegrityError):db.session.commit()
        db.session.rollback()


def test_direct_text_uses_existing_document_revision_and_search(v2app):
    c,h,_=user_client(v2app)
    body='\u1100\u1161상 작품\r\n그는 조용히 문을 열었다. 😀'
    response=c.post('/api/source-documents',headers=h,data={
        'file':(io.BytesIO(body.encode('utf-8')),'직접 입력한 작품.txt'),
        'title':'가상 작품','author':'가상 작가','scope':'PRIVATE',
        'documentType':'TEXT','accessMode':'VIEW'})
    assert response.status_code==201
    d=response.json['data'];did=d['id'];rid=d['latestRevisionId']
    assert d['title']=='가상 작품' and d['author']=='가상 작가'
    detail=c.get('/api/source-documents/'+did).json['data']
    assert detail['content']=='가상 작품\n그는 조용히 문을 열었다. 😀'
    assert detail['documentType']=='TEXT' and detail['scope']=='PRIVATE'
    assert any(item['id']==did for item in c.get('/api/source-documents').json['data'])
    result=c.post('/api/source-documents/'+did+'/search',headers=h,json={'revisionId':rid,'quote':'조용히 문을 열었다'})
    assert result.json['data']['status']=='EXACT_MATCH'
    writing=c.post('/api/writings',headers=h,json={'content':'가상 에세이'}).json['data']
    assert c.post('/api/writings/'+writing['id']+'/documents',headers=h,json={'revisionId':rid}).status_code==200
    other,_,_=user_client(v2app,'synthetic-text-other')
    assert other.get('/api/source-documents/'+did).status_code==404
    assert c.get('/api/files/source/'+did).status_code==404


def test_file_signature_path_traversal_and_active_pdf(v2app):
    c,h,_=user_client(v2app)
    assert c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'not a PDF'),'../../outside.pdf')}).status_code==400
    assert c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'binary\x00file'),'bad.txt')}).status_code==400
    response=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(b'synthetic safe body'),'../../outside.txt')});assert response.status_code==201
    with v2app.app_context():
        doc=db.session.get(SourceDocument,response.json['data']['id']);assert '/' not in doc.stored_name and '..' not in doc.stored_name
        assert (Path(v2app.config['UPLOAD_FOLDER'])/doc.stored_name).is_file()
    pdf=fitz.open();page=pdf.new_page();page.insert_text((72,72),'synthetic PDF')
    pdf.xref_set_key(pdf.pdf_catalog(),'OpenAction','<< /S /JavaScript /JS (synthetic inactive test) >>');data=pdf.tobytes();pdf.close()
    assert c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(data),'active.pdf')}).status_code==400


def test_actual_pdf_and_essay_revision_attachment(v2app):
    c,h,_=user_client(v2app);pdf=fitz.open();pdf.new_page().insert_text((72,72),'synthetic source');data=pdf.tobytes();pdf.close()
    r=c.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(data),'synthetic.pdf')});assert r.status_code==201
    rid=r.json['data']['latestRevisionId']
    writing=c.post('/api/writings',headers=h,json={'content':'synthetic essay'}).json['data']
    assert c.post('/api/writings/'+writing['id']+'/documents',headers=h,json={'revisionId':rid}).status_code==200
    other,oh,_=user_client(v2app,'synthetic-other');writing2=other.post('/api/writings',headers=oh,json={'content':'other essay'}).json['data']
    assert other.post('/api/writings/'+writing2['id']+'/documents',headers=oh,json={'revisionId':rid}).status_code==404


def test_theme_settings_are_private_and_use_same_essay_ids(v2app):
    c,h,_=user_client(v2app);other,oh,_=user_client(v2app,'synthetic-other')
    before=c.post('/api/writings',headers=h,json={'content':'same synthetic essay'}).json['data']
    assert c.patch('/api/settings',headers=h,json={'theme':'bookshelf'}).status_code==200
    assert c.get('/api/settings').json['data']['theme']=='bookshelf'
    assert other.get('/api/settings').json['data']['theme']=='default'
    assert c.get('/api/writings').json['data'][0]['id']==before['id']


def test_authorized_reference_full_pdf_and_narrow_permissions(v2app, monkeypatch):
    import hashlib
    from app.v2.library_api import PRIMARY_REFERENCE
    pdf=fitz.open()
    for _ in range(101): pdf.new_page().insert_text((72,72),'synthetic reference')
    data=pdf.tobytes();pdf.close()
    monkeypatch.setitem(PRIMARY_REFERENCE,'sha256',hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(PRIMARY_REFERENCE,'pdfPageCount',101)
    metadata={'scope':'PUBLIC','documentType':'REFERENCE','accessMode':'DOWNLOAD','rightsConfirmed':'true','rightsInfo':'synthetic approved reference'}
    def send(c,h,body=data,**changes):
        return c.post('/api/source-documents',headers=h,data={**metadata,**changes,'file':(io.BytesIO(body),'reference.pdf')})
    admin,h,_=user_client(v2app,'approved-admin','ADMIN',email='ps25090@onedu.jje.go.kr',verified=True)
    for subject,role,email,verified in [('user','USER','ps25090@onedu.jje.go.kr',True),('other-admin','ADMIN','other@example.test',True),('unverified','ADMIN','ps25090@onedu.jje.go.kr',False)]:
        c,ch,_=user_client(v2app,subject,role,email=email,verified=verified)
        assert send(c,ch).status_code==403
    assert send(admin,h,data+b'changed').status_code==403
    assert send(admin,h,documentType='TEXT').status_code==403
    assert send(admin,h,rightsConfirmed='false').status_code==403
    assert send(admin,h,scope='PRIVATE').status_code==400 # Generic 100-page gate retained.
    first=send(admin,h);assert first.status_code==201
    did=first.json['data']['id'];rid=first.json['data']['latestRevisionId']
    assert first.json['data']['pages']==101
    second=send(admin,h);assert second.status_code==200 and second.json['data']['id']==did
    assert second.json['data']['latestRevisionId']==rid
    student,_,_=user_client(v2app,'reader')
    assert student.get('/api/source-documents/'+did).status_code==200
    assert student.get('/api/files/source/'+did).data==data
    assert admin.post('/api/works',headers=h,json={'title':'Not authorized','scope':'PUBLIC'}).status_code==403
    with v2app.app_context():
        assert SourceDocument.query.count()==1 and DocumentRevision.query.count()==1


def test_supplied_314_page_reference_registration(v2app):
    import hashlib
    from app.analysis.norms_reference import PRIMARY_REFERENCE
    path=Path('C:/Users/USER/Pictures/geulbit_korean_norms_reference_v1.pdf')
    if not path.is_file():pytest.skip('User supplied local reference unavailable')
    data=path.read_bytes();assert hashlib.sha256(data).hexdigest()==PRIMARY_REFERENCE['sha256']
    admin,h,_=user_client(v2app,'real-file-synthetic-admin','ADMIN',email='ps25090@onedu.jje.go.kr',verified=True)
    r=admin.post('/api/source-documents',headers=h,data={'file':(io.BytesIO(data),path.name),'scope':'PUBLIC','documentType':'REFERENCE','accessMode':'DOWNLOAD','rightsConfirmed':'true','rightsInfo':'User approval 2026-10-11'})
    assert r.status_code==201 and r.json['data']['pages']==314
    did=r.json['data']['id'];detail=admin.get('/api/source-documents/'+did).json['data']
    assert len(detail['content'])>200000
    assert admin.get('/api/files/source/'+did).data==data


def test_document_list_batches_latest_ids_without_loading_bodies(v2app):
    from sqlalchemy import event
    c,h,_=user_client(v2app)
    expected={}
    for i in range(12):
        r=upload(c,h,body='synthetic document '+str(i)).json['data']
        expected[r['id']]=r['latestRevisionId']
    did=next(iter(expected))
    r=c.post('/api/source-documents/'+did+'/revisions',headers=h,json={'content':'new synthetic edition','expectedRevisionId':expected[did]})
    assert r.status_code==201;expected[did]=r.json['data']['id']
    statements=[]
    def observe(_conn,_cursor,statement,_parameters,_context,_many):
        if statement.lstrip().upper().startswith('SELECT') and 'document_revisions' in statement:statements.append(statement)
    with v2app.app_context():
        engine=db.engine;event.listen(engine,'before_cursor_execute',observe)
        try:response=c.get('/api/source-documents')
        finally:event.remove(engine,'before_cursor_execute',observe)
    assert {d['id']:d['latestRevisionId'] for d in response.json['data']}==expected
    assert len(statements)==1 and 'document_revisions.content' not in statements[0]
    assert all('content' not in d and 'pageData' not in d for d in response.json['data'])
