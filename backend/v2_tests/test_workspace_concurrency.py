from concurrent.futures import ThreadPoolExecutor
import threading
from sqlalchemy import event
from v2_fixture import v2app, user_client
from app.extensions import db
from app.models import Workspace


def test_first_home_parallel_workspace_and_settings(v2app):
    client, _, owner=user_client(v2app)
    cookie=client.get_cookie('geulbit_session').value
    gate=threading.Barrier(2)
    failures=[]
    def before_insert(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('INSERT INTO WORKSPACE '):
            gate.wait(timeout=5)
    with v2app.app_context():
        engine=db.engine
        event.listen(engine,'before_cursor_execute',before_insert)
    def request(path):
        c=v2app.test_client();c.set_cookie('geulbit_session',cookie)
        return c.get(path).status_code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(request,['/api/workspace','/api/settings']))
        assert result==[200,200]
        with v2app.app_context():
            assert Workspace.query.filter_by(owner_id=owner).count()==1
    finally:
        event.remove(engine,'before_cursor_execute',before_insert)
