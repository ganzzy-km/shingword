from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import time
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from google.auth import crypt, jwt

from backend.components.auth import (AuthDenied, GoogleCodeFlow, Principal,
                                     SessionBoundary, require_private_owner,
                                     require_public_permission, validate_google_claims)
from backend.components.lifecycle import guarded_output, require_retention_policy


def user(**changes):
    return replace(Principal("synthetic-user", "synthetic-sub", "USER", "ACTIVE", 1), **changes)


def claims(**changes):
    now = int(time.time())
    return {"iss": "https://accounts.google.com", "aud": "synthetic-client", "sub": "synthetic-sub",
            "iat": now-1, "exp": now+300, "nonce": "synthetic-nonce", **changes}


@pytest.mark.parametrize("changes", [{"iss": "untrusted"}, {"aud": "other"}, {"nonce": "other"},
                                     {"exp": 0}, {"iat": 9999999999}, {"sub": ""},
                                     {"exp": True}, {"nbf": 9999999999},
                                     {"aud": ["synthetic-client", "other"], "azp": "other"}])
def test_claim_boundaries(changes):
    with pytest.raises(AuthDenied):
        validate_google_claims(claims(**changes), client_id="synthetic-client", nonce="synthetic-nonce", now=time.time())


def test_real_signature_path_with_mock_certificate_and_exchange():
    # A new test-only signing key stays in memory; no Google account/network.
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-oidc-test")])
    current = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                   .serial_number(x509.random_serial_number()).not_valid_before(current-timedelta(minutes=1))
                   .not_valid_after(current+timedelta(hours=1)).sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    signer = crypt.RSASigner.from_string(pem, key_id="synthetic-key")
    cert_response = json.dumps({"synthetic-key": certificate.public_bytes(serialization.Encoding.PEM).decode()}).encode()
    def request(url, **_kwargs):
        assert url == "https://www.googleapis.com/oauth2/v1/certs"
        return SimpleNamespace(status=200, data=cert_response)
    flow = GoogleCodeFlow(client_id="synthetic-client", client_secret="synthetic-client-secret",
                          redirect_uri="https://example.invalid/callback", state_ttl=300, testing=True,
                          exchange=lambda _payload: {"id_token": jwt.encode(signer, claims(nonce=challenge.nonce)).decode()},
                          certificate_request=request)
    url, challenge = flow.begin(now=time.time())
    assert "code_challenge_method=S256" in url and "client_secret" not in url
    identity = flow.finish(challenge, state=challenge.state, code="synthetic-code", now=time.time())
    assert identity["initialRole"] == "USER" and identity["initialStatus"] == "PENDING_APPROVAL"
    with pytest.raises(AuthDenied):
        flow.finish(challenge, state=challenge.state, code="synthetic-code", now=time.time())
    # A token with an invalid signature must fail the real verifier, not just
    # the claim checker. Provider exceptions remain redacted.
    _, challenge = flow.begin(now=time.time())
    flow._exchange = lambda _payload: {"id_token": jwt.encode(signer, claims(nonce=challenge.nonce)).decode()[:-12]+"invalid-signature"}
    with pytest.raises(AuthDenied, match="TOKEN_INVALID"):
        flow.finish(challenge, state=challenge.state, code="synthetic-code", now=time.time())


def test_state_rejection_and_external_default_never_contact_provider():
    flow = GoogleCodeFlow(client_id="synthetic", client_secret="synthetic", redirect_uri="https://example.invalid/callback", state_ttl=300)
    with pytest.raises(AuthDenied, match="PENDING_EXTERNAL"):
        flow.begin(now=time.time())
    calls = []
    flow = GoogleCodeFlow(client_id="synthetic", client_secret="synthetic", redirect_uri="https://example.invalid/callback", state_ttl=300,
                          testing=True, exchange=lambda p:calls.append(p), certificate_request=lambda **k:None)
    _, challenge = flow.begin(now=10)
    with pytest.raises(AuthDenied, match="STATE"):
        flow.finish(challenge, state="wrong", code="synthetic", now=10)
    with pytest.raises(AuthDenied, match="STATE"):
        flow.finish(challenge, state=challenge.state, code="synthetic", now=310)
    assert calls == []

def test_production_exchange_validates_at_verification_time_not_callback_arrival(monkeypatch):
    import backend.components.auth as auth
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    current = datetime.now(timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'synthetic-timing-test')])
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(current-timedelta(minutes=1))
            .not_valid_after(current+timedelta(hours=1)).sign(key, hashes.SHA256()))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    signer = crypt.RSASigner.from_string(pem, key_id='synthetic-timing-key')
    certs = json.dumps({'synthetic-timing-key':cert.public_bytes(serialization.Encoding.PEM).decode()}).encode()
    def certificate_request(url, **kwargs):
        assert url=='https://www.googleapis.com/oauth2/v1/certs'
        return SimpleNamespace(status=200,data=certs)
    flow = GoogleCodeFlow(client_id='synthetic-client',client_secret='synthetic-secret',redirect_uri='https://localhost:8770/api/auth/callback',state_ttl=300,external_approved=True)
    arrival = time.time()-3
    _, challenge = flow.begin(now=arrival-1)
    token = jwt.encode(signer,claims(nonce=challenge.nonce,iat=int(time.time()))).decode()
    def exchange(url, **kwargs):
        assert url=='https://oauth2.googleapis.com/token'
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'id_token':token})
    monkeypatch.setattr('requests.post',exchange);monkeypatch.setattr(auth,'Request',lambda:certificate_request)
    assert flow.finish(challenge,state=challenge.state,code='synthetic-code',now=arrival)['initialStatus']=='PENDING_APPROVAL'

def test_token_exchange_failure_diagnostic_contains_only_constant_stage(monkeypatch,caplog):
    flow=GoogleCodeFlow(client_id='synthetic-client',client_secret='synthetic-secret',redirect_uri='https://localhost:8770/api/auth/callback',state_ttl=300,testing=True,exchange=lambda payload:(_ for _ in ()).throw(RuntimeError('synthetic-secret-sensitive-response')),certificate_request=lambda *args:None)
    _,challenge=flow.begin(now=10)
    with pytest.raises(AuthDenied,match='TOKEN_INVALID'):
        flow.finish(challenge,state=challenge.state,code='synthetic-code',now=11)
    assert 'TOKEN_EXCHANGE' in caplog.text and 'synthetic-secret' not in caplog.text and 'synthetic-code' not in caplog.text

def test_provider_http_failure_logs_allowlisted_reason_only(monkeypatch,caplog):
    import requests
    response=requests.Response();response.status_code=401;response._content=b'{"error":"invalid_client","error_description":"synthetic-sensitive-secret"}'
    def exchange(*args,**kwargs):raise requests.HTTPError('synthetic-sensitive-request',response=response)
    monkeypatch.setattr(requests,'post',exchange)
    flow=GoogleCodeFlow(client_id='synthetic-client',client_secret='synthetic-secret',redirect_uri='https://localhost:8770/api/auth/callback',state_ttl=300,external_approved=True)
    _,challenge=flow.begin(now=10)
    with pytest.raises(AuthDenied,match='TOKEN_INVALID'):flow.finish(challenge,state=challenge.state,code='synthetic-code',now=11)
    assert 'HTTP_401_INVALID_CLIENT' in caplog.text and 'synthetic' not in caplog.text


@pytest.mark.parametrize("status", ["PENDING_APPROVAL", "INACTIVE"])
def test_inactive_and_pending_users_cannot_receive_sessions(status):
    with pytest.raises(AuthDenied):
        SessionBoundary("synthetic-session-secret-not-production", max_age=600).issue(user(status=status))


def test_sessions_csrf_revocation_and_cookie_attributes():
    boundary = SessionBoundary("synthetic-session-secret-not-production", max_age=600)
    cookie, csrf = boundary.issue(user())
    assert boundary.verify(cookie, load_user=lambda _:user(), csrf=csrf, mutating=True).id == user().id
    for value in [None, "wrong"]:
        with pytest.raises(AuthDenied):
            boundary.verify(cookie, load_user=lambda _:user(), csrf=value, mutating=True)
    for principal in [user(session_version=2), user(status="INACTIVE")]:
        with pytest.raises(AuthDenied):
            boundary.verify(cookie, load_user=lambda _:principal)
    with pytest.raises(AuthDenied):
        boundary.verify(cookie+"tampered", load_user=lambda _:user())
    assert boundary.cookie_attributes["secure"] and boundary.cookie_attributes["httponly"]


def test_admin_is_not_owner_and_public_permissions_are_separate():
    admin = user(role="ADMIN")
    with pytest.raises(AuthDenied, match="RESOURCE"):
        require_private_owner(admin, "other-user")
    with pytest.raises(AuthDenied):
        require_public_permission(admin, "ADD")
    require_public_permission(admin, "DELETE")
    writer = user(email="ps00000@onedu.jje.go.kr", email_verified=True)
    require_public_permission(writer, "ADD")
    with pytest.raises(AuthDenied):
        require_public_permission(writer, "DELETE")
    with pytest.raises(AuthDenied):
        require_public_permission(replace(writer, email_verified=False), "ADD")


def test_expiry_race_and_unconfirmed_policy_never_delete():
    with pytest.raises(ValueError, match="UNCONFIRMED"):
        require_retention_policy(None)
    clock = iter([1, 11])
    with pytest.raises(AuthDenied):
        guarded_output(user(), owner_id=user().id, expires_at=10, now=lambda:next(clock), producer=lambda:b"private")


@pytest.mark.parametrize('picture', ['http://lh3.googleusercontent.com/a/photo','https://untrusted.example/photo','javascript:alert(1)','https://lh3.googleusercontent.com:bad/photo','https://user@lh3.googleusercontent.com/photo','https://[bad'])
def test_optional_profile_rejects_untrusted_and_malformed_urls(picture):
    result=validate_google_claims(claims(name='가상 계정',picture=picture),client_id='synthetic-client',nonce='synthetic-nonce',now=time.time())
    assert result['displayName']=='가상 계정' and 'pictureUrl' not in result


def test_profile_cookie_does_not_include_provider_tokens_and_cannot_change_role():
    boundary=SessionBoundary('synthetic-session-secret-not-production',max_age=600)
    cookie,_=boundary.issue(user(),profile={'displayName':'가상 계정','pictureUrl':'https://lh3.googleusercontent.com/a/photo','role':'ADMIN','id_token':'synthetic-token'})
    value=boundary.serializer.loads(cookie)
    assert value['profile']=={'displayName':'가상 계정','pictureUrl':'https://lh3.googleusercontent.com/a/photo'}
    assert boundary.verify(cookie,load_user=lambda _:user()).role=='USER'
