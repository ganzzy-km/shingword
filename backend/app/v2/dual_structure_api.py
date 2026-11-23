"""Optional structure analysis on saved versions, with private SQLite receipts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import re
import sqlite3
import threading

from flask import Blueprint, abort, current_app, g, request
from sqlalchemy import or_
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import load_only

from components.structure_contract import (
    MAP_VERSION, MAX_PARAGRAPHS, PROMPT_VERSION, adapt_s4, compare_structures, digest,
    structure_map, text_hash, validate_paragraph_ai,
)
from ..extensions import db
from ..models import (
    Analysis, AppSetting, Consent, DocumentRevision, EssayDocument, EssayStructureMap,
    EssayStructureRun, SourceDocument, User, Writing, WritingVersion,
)
from ..utils import api_error, json_body, success
from .ai_api import enabled, reserve_budget
from .analysis_api import owned_run
from .baze_provider import ProviderUnavailable
from .common import iso, owned_writing

bp = Blueprint('dual_structure', __name__, url_prefix='/api')
CONSENT_KIND = 'AI_STRUCTURE'
ACTIVE = ('QUEUED', 'RUNNING')
MAX_MAP_CODEPOINTS = 200_000
WORKERS = 2
executor = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix='structure-ai')
capacity = threading.BoundedSemaphore(WORKERS)
IDENTIFIERS = re.compile(
    r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?:\+82[- .]?)?0?1[016789][- .]?\d{3,4}[- .]?\d{4}'
    r'|\b\d{6}\s*[-–]?\s*[1-8]\d{6}\b|https?://\S+'
    r'|(?:학생\s*이름|성명|이름|학번|전화번호|주소|생년월일|소속\s*학교|반\s*번호|name|student\s*id)\s*[:：]'
    r'|\b(?:name\s+is|I\s+am\s+called)\b|제\s*이름은|저는\s+[가-힣]{2,4}\s*(?:입니다|이에요)', re.I)

MESSAGES = {
    'AI_DISABLED': '외부 AI 구조 분석이 준비되지 않았습니다.',
    'AI_CONSENT_REQUIRED': '외부 전송 동의를 확인해 주세요.',
    'AI_INPUT_LIMIT': 'AI 분석에 보낼 수 있는 글 길이 또는 문단 수를 초과했습니다.',
    'AI_PROTECTED_SOURCE': '보호 자료와 연결된 판본은 외부 AI로 전송할 수 없습니다.',
    'AI_PREVIEW_MISMATCH': '전송할 문단을 다시 확인해 주세요.',
    'AI_NO_INPUT': '전송할 수 있는 문단이 없습니다.',
    'AI_BUSY': 'AI 구조 분석이 실행 중입니다. 잠시 후 다시 시도해 주세요.',
    'AI_BUDGET_LIMIT': 'AI 요청 또는 비용 한도에 도달했습니다.',
    'STRUCTURE_STALE': '이전 판본입니다. 현재 글을 저장한 뒤 다시 선택해 주세요.',
    'STRUCTURE_MAP_LIMIT': '이 판본은 구조 보기에서 처리할 수 있는 길이를 초과합니다.',
    'STRUCTURE_VERSION_INVALID': '저장 판본의 원문을 확인할 수 없습니다.',
}


@bp.before_request
def bound_dual_request():
    if request.method == 'POST':
        request.max_content_length = 16 * 1024


def now():
    return datetime.now(timezone.utc)


def write_transaction():
    # Auth may have opened a reader. Serialize consent, ownership, budget and
    # dispatch bookkeeping before sending. Never hold a transaction over I/O.
    db.session.rollback()
    db.session.execute(db.text('BEGIN IMMEDIATE'))


def optional_lock_error(error):
    code = getattr(error.orig, 'sqlite_errorcode', 0)
    if (code & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        db.session.rollback()
        return scope_error(ValueError('AI_BUSY'))
    raise error


def version_for(identifier):
    if not isinstance(identifier, str) or len(identifier) != 36:
        abort(404, description='API resource unavailable')
    version = db.session.get(WritingVersion, identifier)
    if not version or not version.snapshot_hash:
        abort(404, description='API resource unavailable')
    item = owned_writing(version.writing_id)
    if text_hash(version.content) != version.snapshot_hash:
        raise ValueError('STRUCTURE_VERSION_INVALID')
    return item, version


def is_current(item, version):
    return item.current_version_id == version.id and item.content == version.content


def structure_map_for(version):
    saved = db.session.get(EssayStructureMap, version.id)
    if saved and (saved.body_hash != version.snapshot_hash or saved.map_version != MAP_VERSION):
        raise ValueError('STRUCTURE_VERSION_INVALID')
    if saved and saved.sentence_map is not None and saved.quotation_ranges is not None:
        return saved.sentence_map, saved.quotation_ranges
    if len(version.content) > MAX_MAP_CODEPOINTS:
        raise ValueError('STRUCTURE_MAP_LIMIT')
    mapping, quotes = structure_map(version.content)
    return mapping, quotes


def save_map(version, mapping, quotes):
    statement = insert(EssayStructureMap).values(version_id=version.id, body_hash=version.snapshot_hash,
        map_version=MAP_VERSION, sentence_map=mapping, quotation_ranges=quotes)
    db.session.execute(statement.on_conflict_do_update(index_elements=['version_id'],
        set_={'sentence_map': statement.excluded.sentence_map, 'quotation_ranges': statement.excluded.quotation_ranges},
        where=EssayStructureMap.sentence_map.is_(None)))


def linked_protected(writing_id):
    return db.session.query(SourceDocument.id).join(DocumentRevision,
        DocumentRevision.document_id == SourceDocument.id).join(EssayDocument,
        EssayDocument.revision_id == DocumentRevision.id).filter(EssayDocument.writing_id == writing_id,
        or_(SourceDocument.access_mode == 'MATCH_ONLY', SourceDocument.rights_confirmed.is_not(True))).first() is not None


def pin_protected_version(version):
    # Freeze the denial even if the document is detached later. The ordinary
    # S4/essay save still uses its existing immutable-version transaction.
    if linked_protected(version.writing_id):
        statement = insert(EssayStructureMap).values(version_id=version.id, body_hash=version.snapshot_hash,
            map_version=MAP_VERSION, protected_source=True, sentence_map=db.null(), quotation_ranges=db.null())
        db.session.execute(statement.on_conflict_do_update(index_elements=['version_id'], set_={'protected_source': True}))


def protected(item, version):
    saved = db.session.get(EssayStructureMap, version.id)
    if (saved and saved.protected_source) or linked_protected(item.id):
        return True
    # Earlier S4 manifests can prove a historical MATCH_ONLY binding after a
    # source has been detached. This metadata is used only for denial.
    old_binding = db.session.execute(db.text('''
        SELECT 1 FROM analysis, json_each(analysis.context_snapshot, '$.documents') AS linked
        WHERE analysis.essay_version_id = :version
          AND json_extract(linked.value, '$.accessMode') = 'MATCH_ONLY' LIMIT 1
        '''), {'version': version.id})
    return old_binding.first() is not None


def policy_version():
    policy = current_app.config.get('AI_STRUCTURE_POLICY_VERSION')
    return policy if isinstance(policy, str) and 0 < len(policy) <= 128 else None


def provider_for():
    if (current_app.config.get('AI_STRUCTURE_ENABLED') is True and policy_version()
            and current_app.config.get('EXTERNAL_AI_TERMS_APPROVED') is True and enabled()):
        return current_app.extensions.get('structure_provider')
    return None


def consent_for(uid):
    return Consent.query.filter_by(user_id=uid, kind=CONSENT_KIND, policy_version=policy_version()).filter(
        Consent.granted_at.is_not(None), Consent.revoked_at.is_(None)).order_by(Consent.created_at.desc()).first()


def scope_error(error):
    code = str(error)
    if code not in MESSAGES:
        return api_error('VALIDATION_ERROR', '구조 분석 요청을 확인해 주세요.')
    status = {'AI_DISABLED': 503, 'AI_CONSENT_REQUIRED': 403, 'AI_PROTECTED_SOURCE': 403,
              'AI_BUSY': 429, 'AI_BUDGET_LIMIT': 429, 'STRUCTURE_STALE': 409,
              'STRUCTURE_VERSION_INVALID': 409, 'AI_PREVIEW_MISMATCH': 409,
              'AI_INPUT_LIMIT': 413, 'STRUCTURE_MAP_LIMIT': 413}.get(code, 400)
    return api_error(code, MESSAGES[code], status)


def build_preview(item, version, mapping, excluded, user, provider):
    if not is_current(item, version):
        raise ValueError('STRUCTURE_STALE')
    if protected(item, version):
        raise ValueError('AI_PROTECTED_SOURCE')
    paragraphs = mapping['paragraphs']
    if len(paragraphs) > MAX_PARAGRAPHS or len(version.content) > provider.settings.max_selected_codepoints:
        raise ValueError('AI_INPUT_LIMIT')
    if (not isinstance(excluded, list) or len(excluded) > len(paragraphs)
            or any(not isinstance(pid, str) for pid in excluded)
            or len(set(excluded)) != len(excluded)
            or set(excluded) - {row['id'] for row in paragraphs}):
        raise ValueError()
    exclude_set = set(excluded)
    sent, omitted = [], []
    # Scan the original before slicing so every intersecting paragraph is withheld.
    identifiers = [match.span() for match in IDENTIFIERS.finditer(version.content)]
    if user.email:
        identifiers.extend(match.span() for match in re.finditer(re.escape(user.email), version.content, re.I))
    identifiers.sort()
    position = 0
    for row in paragraphs:
        while position < len(identifiers) and identifiers[position][1] <= row['start']:
            position += 1
        if position < len(identifiers) and identifiers[position][0] < row['end']:
            omitted.append(row['id'])
        elif row['id'] not in exclude_set:
            sent.append({'id': row['id'], 'text': version.content[row['start']:row['end']]})
    if not sent:
        raise ValueError('AI_NO_INPUT')
    if not provider.structure_fits(sent):
        raise ValueError('AI_INPUT_LIMIT')
    settings = {'providerProfile': provider.cache_tag, 'model': provider.settings.model, 'policy': policy_version(),
                'outputTokens': provider.settings.max_completion_tokens, 'timeoutSeconds': provider.settings.timeout_seconds,
                'maximumCodePoints': provider.settings.max_selected_codepoints, 'mapVersion': MAP_VERSION, 'inputUnit': 'paragraph',
                'manualExclusions': sorted(exclude_set), 'automaticExclusions': omitted}
    notice = current_app.config.get('AI_STRUCTURE_POLICY_NOTICE')
    if notice:
        settings['policyNoticeHash'] = text_hash(notice)
    key = digest({'user': user.id, 'version': version.id, 'bodyHash': version.snapshot_hash,
                  'prompt': PROMPT_VERSION, 'settings': settings, 'paragraphs': sent})
    return sent, settings, key


def effective_status(row):
    if row.status in ACTIVE and row.deadline_at.replace(tzinfo=timezone.utc) <= now():
        return 'FAILED', 'AI_INTERRUPTED_OR_TIMEOUT'
    return row.status, row.error_code if row.status not in ACTIVE else None


def dto(row):
    if not row:
        return None
    status, error = effective_status(row)
    return {'id': row.id, 'versionId': row.version_id, 'engine': row.engine, 'provider': row.provider,
            'model': row.model, 'promptVersion': row.prompt_version, 'status': status,
            'createdAt': iso(row.created_at), 'completedAt': iso(row.completed_at),
            'errorCode': error, 'result': row.result if status == 'COMPLETED' else None,
            'inputUnit': row.settings.get('inputUnit', 'sentence'),
            'settings': {key: row.settings[key] for key in ('manualExclusions', 'automaticExclusions')},
            'usage': row.usage, 'reservedCostUnits': row.reserved_cost_units}


def runs_for(item, version):
    return EssayStructureRun.query.filter_by(user_id=item.owner_id, writing_id=item.id,
                                            version_id=version.id, body_hash=version.snapshot_hash)


@bp.get('/writing-versions/<identifier>/structure')
def get_structure(identifier):
    try:
        item, version = version_for(identifier)
        mapping, quotes = structure_map_for(version)
        rows = runs_for(item, version)
        run_id = request.args.get('runId')
        latest = rows.order_by(EssayStructureRun.created_at.desc(), EssayStructureRun.id)
        row = rows.filter_by(id=run_id).first_or_404(description='API resource unavailable') if run_id else latest.first()
        history = latest.options(load_only(EssayStructureRun.id, EssayStructureRun.status, EssayStructureRun.model,
            EssayStructureRun.created_at, EssayStructureRun.deadline_at, EssayStructureRun.error_code)).limit(20).all()
        selected = request.args.get('analysisId')
        s4 = None
        if selected:
            run = owned_run(selected, saved_read=True)
            snapshot = run.result_snapshot or {}
            if run.essay_version_id != version.id or run.writing_id != item.id:
                abort(404, description='API resource unavailable')
            if run.status == 'completed' and snapshot.get('input', {}).get('sha256') == version.snapshot_hash:
                s4 = adapt_s4(snapshot, mapping['sentences'], len(version.content))
        ai = dto(row)
        comparison = compare_structures(s4, ai['result']) if s4 is not None and ai and ai['result'] else None
        return success({'versionId': version.id, 'bodyHash': version.snapshot_hash, 'offsetUnit': 'unicode-code-point',
            'sourceText': version.content,
            'versionStatus': 'CURRENT' if is_current(item, version) else 'STALE', **mapping,
            'quotations': quotes, 's4': s4, 'ai': ai, 'comparison': comparison,
            'history': [{'id': entry.id, 'model': entry.model, 'status': effective_status(entry)[0],
                         'createdAt': iso(entry.created_at)} for entry in history],
            'available': provider_for() is not None, 'consented': consent_for(item.owner_id) is not None,
            'revocable': Consent.query.filter_by(user_id=item.owner_id, kind=CONSENT_KIND, revoked_at=None).first() is not None,
            'policyVersion': policy_version(), 'provider': 'BAZE (Mindlogic)'})
    except ValueError as error:
        return scope_error(error)


@bp.get('/writing-versions/<identifier>/structure/ai/<run_id>')
def get_status(identifier, run_id):
    try:
        item, version = version_for(identifier)
        row = runs_for(item, version).filter_by(id=run_id).first_or_404(description='API resource unavailable')
        return success(dto(row))
    except ValueError as error:
        return scope_error(error)


@bp.post('/structure/consent')
def set_consent():
    data, error = json_body()
    if error:
        return error
    policy = policy_version()
    if set(data) != {'granted', 'policyVersion'} or type(data['granted']) is not bool:
        return scope_error(ValueError())
    if data['granted'] and (not policy or data['policyVersion'] != policy or not provider_for()):
        return scope_error(ValueError('AI_DISABLED'))
    try:
        write_transaction()
        stamp = now()
        active = Consent.query.filter_by(user_id=g.principal.id, kind=CONSENT_KIND, revoked_at=None).all()
        if data['granted'] and any(row.policy_version == policy for row in active):
            db.session.rollback()
            return success({'granted': True, 'policyVersion': policy})
        for row in active:
            row.revoked_at = stamp
        if data['granted']:
            db.session.add(Consent(user_id=g.principal.id, kind=CONSENT_KIND, policy_version=policy, granted_at=stamp))
        db.session.commit()
        return success({'granted': data['granted'], 'policyVersion': policy})
    except OperationalError as error:
        return optional_lock_error(error)


@bp.post('/writing-versions/<identifier>/structure/preview')
def preview(identifier):
    data, error = json_body()
    if error:
        return error
    try:
        item, version = version_for(identifier)
        if set(data) != {'excludeParagraphIds'}:
            raise ValueError()
        provider = provider_for()
        if not provider:
            raise ValueError('AI_DISABLED')
        mapping, _ = structure_map_for(version)
        sent, settings, key = build_preview(item, version, mapping, data['excludeParagraphIds'],
                                            db.session.get(User, item.owner_id), provider)
        return success({'paragraphs': sent, 'omittedParagraphIds': settings['automaticExclusions'],
                        'previewHash': key, 'policyVersion': settings['policy'], 'provider': 'BAZE (Mindlogic)',
                        'model': settings['model'], 'policyNotice': current_app.config.get('AI_STRUCTURE_POLICY_NOTICE')})
    except ValueError as error:
        return scope_error(error)


def mark_finished(row, status, code=None, result=None, usage=None):
    row.status, row.error_code, row.result, row.usage = status, code, result, usage
    row.completed_at = now()


def expire_pending():
    db.session.execute(db.update(EssayStructureRun).where(EssayStructureRun.status.in_(ACTIVE),
        EssayStructureRun.deadline_at <= now()).values(status='FAILED', error_code='AI_INTERRUPTED_OR_TIMEOUT', completed_at=now()))


def worker_inputs(row, provider):
    user = db.session.get(User, row.user_id)
    item = db.session.get(Writing, row.writing_id)
    version = db.session.get(WritingVersion, row.version_id)
    consent = consent_for(row.user_id)
    if (not user or user.status != 'ACTIVE' or user.session_version != row.settings['sessionVersion']
            or not item or item.owner_id != row.user_id or (item.expires_at and item.expires_at.replace(tzinfo=timezone.utc) <= now())
            or not version or version.writing_id != item.id or version.snapshot_hash != row.body_hash
            or text_hash(version.content) != row.body_hash):
        raise ValueError('STRUCTURE_ACCESS_CHANGED')
    if not consent or consent.id != row.settings['consentId']:
        raise ValueError('AI_CONSENT_REQUIRED')
    if not provider or row.deadline_at.replace(tzinfo=timezone.utc) <= now():
        raise ValueError('AI_INTERRUPTED_OR_TIMEOUT')
    if row.prompt_version != PROMPT_VERSION:
        raise ValueError('AI_PREVIEW_MISMATCH')
    mapping, quotes = structure_map_for(version)
    sent, _, key = build_preview(item, version, mapping, row.settings['manualExclusions'], user, provider)
    if key != row.cache_key:
        raise ValueError('AI_PREVIEW_MISMATCH')
    return version.content, mapping, quotes, sent


SAFE_CODES = set(MESSAGES) | {'STRUCTURE_ACCESS_CHANGED', 'AI_INTERRUPTED_OR_TIMEOUT', 'AI_TIMEOUT',
    'AI_PROVIDER_REFUSED', 'AI_SCHEMA_INVALID', 'AI_MODEL_MISMATCH', 'AI_PROVIDER_UNAVAILABLE', 'AI_SPAN_INVALID',
    'AI_PARAGRAPH_INVALID', 'AI_QUOTATION_INVALID', 'AI_NODE_INVALID', 'AI_RELATION_INVALID'}
REVIEW_CODES = {'AI_PROVIDER_REFUSED', 'AI_SCHEMA_INVALID', 'AI_MODEL_MISMATCH', 'AI_SPAN_INVALID', 'AI_PARAGRAPH_INVALID',
                'AI_QUOTATION_INVALID', 'AI_NODE_INVALID', 'AI_RELATION_INVALID'}


def run_job(app, run_id):
    try:
        with app.app_context():
            usage, result, failure = None, None, None
            try:
                write_transaction()
                row = db.session.get(EssayStructureRun, run_id)
                if not row or row.status != 'QUEUED':
                    return
                provider = provider_for()
                body, mapping, quotes, sent = worker_inputs(row, provider)
                row.status = 'RUNNING'
                db.session.commit()
                db.session.remove()
                value, usage = provider.structure(sent)
                result = validate_paragraph_ai(value, body, mapping, quotes, {entry['id'] for entry in sent})
            except ProviderUnavailable as error:
                failure, usage = str(error), error.usage
            except ValueError as error:
                failure = str(error)
            except Exception:
                failure = 'AI_PROVIDER_UNAVAILABLE'
            try:
                write_transaction()
                row = db.session.get(EssayStructureRun, run_id)
                if not row or row.status not in ACTIVE:
                    return
                if row.status == 'RUNNING':
                    try:
                        worker_inputs(row, provider_for())
                    except ValueError as error:
                        failure = str(error)
                if failure:
                    code = failure if failure in SAFE_CODES else 'AI_PROVIDER_UNAVAILABLE'
                    mark_finished(row, 'REVIEW_REQUIRED' if code in REVIEW_CODES else 'FAILED', code, usage=usage)
                else:
                    mark_finished(row, 'COMPLETED', result=result, usage=usage)
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.error('Structure AI job persistence failed')
    finally:
        capacity.release()


@bp.post('/writing-versions/<identifier>/structure/ai')
def start(identifier):
    data, error = json_body()
    if error:
        return error
    acquired = False
    try:
        if (set(data) != {'excludeParagraphIds', 'reviewed', 'previewHash'} or data['reviewed'] is not True
                or not isinstance(data['previewHash'], str) or len(data['previewHash']) != 64):
            raise ValueError()
        # Reject a bad ID without taking SQLite's writer lock.
        version_for(identifier)
        write_transaction()
        item, version = version_for(identifier)
        provider = provider_for()
        if not provider:
            raise ValueError('AI_DISABLED')
        consent = consent_for(item.owner_id)
        if not consent:
            raise ValueError('AI_CONSENT_REQUIRED')
        mapping, quotes = structure_map_for(version)
        _, settings, key = build_preview(item, version, mapping, data['excludeParagraphIds'],
                                         db.session.get(User, item.owner_id), provider)
        if key != data['previewHash']:
            raise ValueError('AI_PREVIEW_MISMATCH')
        expire_pending()
        cached = runs_for(item, version).filter(EssayStructureRun.cache_key == key,
                                                EssayStructureRun.status.in_((*ACTIVE, 'COMPLETED'))).first()
        if cached:
            response = dto(cached)
            db.session.commit()
            return success({**response, 'cached': True}, status=200 if response['status'] == 'COMPLETED' else 202)
        configured = db.session.get(AppSetting, 'ai_limits')
        limits = configured.value if configured else current_app.config.get('AI_LIMITS')
        ceiling = limits.get('concurrency') if isinstance(limits, dict) else None
        active = EssayStructureRun.query.filter(EssayStructureRun.status.in_(ACTIVE))
        if (type(ceiling) is not int or ceiling < 1 or active.count() >= min(ceiling, WORKERS)
                or active.filter_by(user_id=item.owner_id).first() or not capacity.acquire(blocking=False)):
            raise ValueError('AI_BUSY')
        acquired = True
        cost = current_app.config.get('AI_STRUCTURE_CALL_COST_UNITS')
        if type(cost) is not int or cost < 1 or not reserve_budget(item.owner_id, call_cost=cost, commit=False):
            raise ValueError('AI_BUDGET_LIMIT')
        save_map(version, mapping, quotes)
        row = EssayStructureRun(user_id=item.owner_id, writing_id=item.id, version_id=version.id,
            body_hash=version.snapshot_hash, cache_key=key, provider='BAZE', model=settings['model'],
            prompt_version=PROMPT_VERSION, settings={**settings, 'consentId': consent.id,
            'sessionVersion': g.principal.session_version}, status='QUEUED', reserved_cost_units=cost,
            deadline_at=now() + timedelta(seconds=provider.settings.timeout_seconds + 10))
        db.session.add(row)
        db.session.flush()
        response = dto(row)
        db.session.commit()
        app = current_app._get_current_object()
        try:
            executor.submit(run_job, app, response['id'])
            acquired = False  # Worker owns the slot from here.
        except RuntimeError:
            mark_finished(row, 'FAILED', 'AI_PROVIDER_UNAVAILABLE')
            db.session.commit()
            return scope_error(ValueError('AI_DISABLED'))
        return success({**response, 'cached': False}, status=202)
    except ValueError as error:
        db.session.rollback()
        return scope_error(error)
    except OperationalError as error:
        return optional_lock_error(error)
    finally:
        if acquired:
            capacity.release()
