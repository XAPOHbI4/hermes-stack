#!/usr/bin/env python3
"""Личная очередь разбора звонков. SQLite + один systemd worker, без брокера."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(os.environ.get('SA_CALL_ROOT', '/var/lib/sales-assistant-stt'))
HERMES = Path('/root/.hermes')
ALLOWED = [HERMES / 'audio_cache', HERMES / 'cache/audio', HERMES / 'cache/documents', HERMES / 'document_cache']
if os.environ.get('SA_ACCEPTANCE') == '1':
    ALLOWED.append(Path('/var/lib/sales-assistant-stt/acceptance'))


class DeliveryUnknown(Exception):
    """Telegram мог принять сообщение; автоматический повтор создаст дубликат."""


class MessageUnavailable(Exception):
    """The known placeholder was deleted or cannot be edited."""


def connect():
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    db = sqlite3.connect(ROOT / 'queue.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('BEGIN IMMEDIATE')
    db.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, state TEXT NOT NULL, source TEXT NOT NULL,
        context TEXT NOT NULL, transcript TEXT, report TEXT,
        attempts INTEGER NOT NULL DEFAULT 0, due REAL NOT NULL DEFAULT 0,
        error TEXT, message_id INTEGER, notice_message_id INTEGER, created REAL NOT NULL, updated REAL NOT NULL)''')
    if 'status_message_id' not in [r[1] for r in db.execute('PRAGMA table_info(jobs)')]:
        db.execute('ALTER TABLE jobs ADD COLUMN status_message_id INTEGER')
    columns = [r[1] for r in db.execute('PRAGMA table_info(jobs)')]
    for name, sql_type in [('outcome', 'TEXT'), ('outcome_note', 'TEXT'),
                           ('outcome_updated', 'REAL')]:
        if name not in columns:
            db.execute('ALTER TABLE jobs ADD COLUMN ' + name + ' ' + sql_type)
    db.commit()
    return db


def change(db, job_id, **fields):
    fields['updated'] = time.time()
    db.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?',
               [*fields.values(), job_id])
    db.commit()


def command(args, timeout, env=None):
    with subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          start_new_session=True, env=env) as proc:
        try:
            out, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
            raise RuntimeError('process_timeout') from None
        if proc.returncode:
            raise RuntimeError('media_process_failed')
    return out


def probe(path):
    result = json.loads(command(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
        '-show_entries', 'format=duration:stream=codec_type', '-of', 'json', str(path)], 20))
    duration = float(result.get('format', {}).get('duration', 0))
    if not 1 <= duration <= 3600 or not any(s.get('codec_type') == 'audio' for s in result.get('streams', [])):
        raise ValueError('audio_duration_or_format')
    return duration


def validate_input(path):
    path = Path(path).resolve(strict=True)
    if not any(path.is_relative_to(root.resolve()) for root in ALLOWED):
        raise ValueError('only_telegram_audio_cache_allowed')
    if not path.is_file() or not 0 < path.stat().st_size <= 100 * 1024**2:
        raise ValueError('audio_size_limit_100mb')
    probe(path)
    return path


def enqueue(db, path, context='', notify=False):
    path = validate_input(path)
    if len(context) > 2000:
        raise ValueError('context_too_long')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = db.execute('SELECT id,state,status_message_id FROM jobs WHERE id=?', (digest,)).fetchone()
    if existing:
        return dict(existing)
    if shutil.disk_usage(ROOT).free < 2 * 1024**3:
        raise ValueError('disk_below_2gb')
    recordings = ROOT / 'recordings'
    recordings.mkdir(mode=0o700, exist_ok=True)
    # File first, transaction second: a crash may leave a preserved orphan, never a lost queued source.
    suffix = path.suffix if re.fullmatch(r'\.[a-zA-Z0-9]{1,5}', path.suffix) else '.audio'
    target = recordings / (digest + suffix)
    with tempfile.NamedTemporaryFile(dir=recordings, delete=False) as tmp:
        with path.open('rb') as source:
            shutil.copyfileobj(source, tmp)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, target)
    now = time.time()
    inserted = db.execute('INSERT OR IGNORE INTO jobs(id,state,source,context,created,updated) VALUES(?,?,?,?,?,?)',
               (digest, 'announcing' if notify else 'queued', str(target), context, now, now)).rowcount
    db.commit()
    if notify and inserted:
        try:
            prefix = 'ТЕСТ MVP — вымышленная запись.\n\n' if context.startswith('[ТЕСТ MVP]') else ''
            message_id = send_report(prefix + 'Запись принята в очередь на расшифровку. '
                'Готовый разбор появится вместо этого сообщения.')
        except DeliveryUnknown:
            change(db, digest, state='delivery_unknown', error='status_delivery_unconfirmed')
        except RuntimeError:
            # Confirmed rejection: no placeholder exists, so legacy delivery remains safe.
            change(db, digest, state='queued', error='status_send_failed')
        except Exception:
            change(db, digest, state='delivery_unknown', error='status_delivery_unconfirmed')
        else:
            change(db, digest, state='queued', status_message_id=message_id)
    return dict(db.execute('SELECT id,state,status_message_id FROM jobs WHERE id=?', (digest,)).fetchone())


def transcribe(source, job_id):
    import fcntl
    # Shared with native Hermes voice STT: one recognition per file, one CPU job at a time.
    with (ROOT/'stt.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        config = Path(__file__).with_name('stt-backend.txt')
        backend = config.read_text().strip() if config.is_file() else 'cpu'
        if backend == 'mac':
            import mac_stt
            return mac_stt.transcribe(source, job_id, ROOT)
        if backend != 'cpu':
            raise ValueError('invalid_stt_backend')
        cached = ROOT/'transcripts'/(job_id+'.txt')
        if cached.is_file() and len(cached.read_text().strip()) >= 15:
            return cached.read_text().strip()
        return transcribe_uncached(source, job_id)


def transcribe_uncached(source, job_id):
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='call-', dir=ROOT) as tmp:
        wav, output = Path(tmp) / 'audio.wav', Path(tmp) / 'transcript'
        command(['ffmpeg', '-nostdin', '-y', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                 '-i', source, '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(wav)], 180)
        import wave
        import audioop
        with wave.open(str(wav)) as audio:
            if audioop.rms(audio.readframes(audio.getnframes()), 2) < 40:
                raise RuntimeError('no_audible_speech')
        command(['/opt/sales-assistant-stt/venv/bin/python',
                 str(Path(__file__).with_name('stt.py')), str(wav), str(output)], 3600)
        text = output.with_suffix('.txt').read_text().strip()
        if len(text) < 15 or len(text) > 120000:
            raise RuntimeError('transcript_length_invalid')
        folder = ROOT / 'transcripts'
        folder.mkdir(mode=0o700, exist_ok=True)
        for extension in ['.srt', '.txt']:
            with tempfile.NamedTemporaryFile(dir=folder,delete=False) as saved:
                saved.write(output.with_suffix(extension).read_bytes())
                saved.flush();os.fsync(saved.fileno())
            os.replace(saved.name,folder/(job_id+extension))
    print(json.dumps({'stage': 'stt', 'id': job_id[:12], 'seconds': round(time.monotonic()-started, 2)}), flush=True)
    return text


def settings():
    from dotenv import dotenv_values
    import yaml
    env = dotenv_values(HERMES / '.env')
    cfg = yaml.safe_load((HERMES / 'config.yaml').read_text())
    model = cfg['model']
    key = model.get('api_key') or env.get('OPENAI_API_KEY')
    if isinstance(key, str) and key.startswith('$'):
        key = env.get(key.lstrip('$').strip('{}'))
    owners = re.findall(r'-?\d+', env.get('TELEGRAM_ALLOWED_USERS') or '')
    if len(owners) != 1 or not key or not env.get('TELEGRAM_BOT_TOKEN'):
        raise RuntimeError('owner_or_credentials_not_configured')
    from urllib.parse import urlparse
    url = model['base_url']
    if urlparse(url).hostname not in ['127.0.0.1', 'localhost']:
        raise RuntimeError('expected_existing_local_proxy')
    return model, key, owners[0], env['TELEGRAM_BOT_TOKEN']


def normalized(text):
    return ' '.join(text.casefold().replace('ё', 'е').split())


def coaching_history(db, job_id, limit=5):
    rows = db.execute('''SELECT report,outcome,outcome_note,created FROM jobs
        WHERE id<>? AND state='delivered' AND report IS NOT NULL
        ORDER BY created DESC LIMIT ?''', (job_id, limit)).fetchall()
    return [{'report': row['report'][:2200], 'outcome': row['outcome'] or '',
             'outcome_note': (row['outcome_note'] or '')[:300]}
            for row in reversed(rows)]


def save_outcome(db, status, job_id=None, message_id=None, note=''):
    allowed = {'follow_up', 'meeting_set', 'visited', 'sold', 'lost', 'no_contact'}
    if status not in allowed or len(note) > 500:
        raise ValueError('invalid_outcome')
    if job_id:
        row = db.execute('SELECT id FROM jobs WHERE id=?', (job_id,)).fetchone()
    elif message_id is not None:
        row = db.execute('SELECT id FROM jobs WHERE message_id=?', (message_id,)).fetchone()
    else:
        row = db.execute("SELECT id FROM jobs WHERE state='delivered' ORDER BY created DESC LIMIT 1").fetchone()
    if not row:
        raise ValueError('job_not_found')
    change(db, row['id'], outcome=status, outcome_note=note, outcome_updated=time.time())
    return {'id': row['id'], 'outcome': status}


def render(data, transcript):
    required = ['opening', 'client_signal', 'turning_point', 'main_point_title', 'main_point', 'better_phrase',
                'diagnostic_question', 'next_step', 'root_cause']
    for key in required:
        limit = 600 if key == 'better_phrase' else 450
        if not isinstance(data.get(key), str) or len(data[key]) > limit or not data[key].strip():
            raise ValueError('invalid_report_field')
    if data['main_point_title'] not in ('Главная ошибка', 'Главный удачный ход'):
        raise ValueError('invalid_main_point_title')
    trend = data.get('trend', '')
    if not isinstance(trend, str) or len(trend) > 450:
        raise ValueError('invalid_report_field')
    parts = [data['opening'], '\nСигнал клиента: ' + data['client_signal'],
             '\nПоворотный момент: ' + data['turning_point'],
             '\n' + data['main_point_title'] + ': ' + data['main_point']]
    for key, title in [('strengths', 'Что было хорошо:'), ('improvements', 'Что надо менять:')]:
        items = data.get(key)
        if not isinstance(items, list) or len(items) > 2:
            raise ValueError('invalid_report_items')
        parts.append('\n' + title)
        if not items:
            parts.append('Недостаточно оснований для отдельного вывода.' if key == 'strengths' else 'Явных ошибок по этому материалу не выявлено.')
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError('invalid_report_item')
            quote, observation = item.get('quote'), item.get('observation')
            if not isinstance(quote, str) or not 3 <= len(quote) <= 180 or normalized(quote) not in normalized(transcript):
                raise ValueError('quote_not_in_transcript')
            if not isinstance(observation, str) or not 1 <= len(observation) <= 300:
                raise ValueError('invalid_observation')
            parts.append(('\n' if index else '') + '• ' + observation)
    if trend.strip():
        parts.append('\nПовторяющийся паттерн: ' + trend)
    parts.extend(['\nФраза для следующего такого звонка:\n' + data['better_phrase'],
                  '\nДиагностический вопрос:\n' + data['diagnostic_question'],
                  '\nСледующий шаг:\n' + data['next_step'],
                  '\nКорень по «5 почему»: ' + data['root_cause']])
    result = '\n'.join(parts)
    if len(result) > 3800:
        raise ValueError('report_too_long')
    return result


def analyse(transcript, context, history=None):
    from openai import OpenAI
    model, key, _, _ = settings()
    client = OpenAI(api_key=key, base_url=model['base_url'], timeout=180, max_retries=0)
    try:
        result = client.chat.completions.create(model=model.get('default') or model['name'],
            messages=[{'role':'system','content':Path(__file__).with_name('coach.md').read_text()},
                      {'role':'user','content':json.dumps({'transcript':transcript,'context':context,
                                                         'previous_reviews':history or []},ensure_ascii=False)}])
        content = result.choices[0].message.content or ''
        data = json.loads(content)
        report=render(data, transcript)
        return ('ТЕСТ MVP — вымышленный звонок\n\n' if context.startswith('[ТЕСТ MVP]') else '')+report
    finally:
        client.close()


def telegram_entities(text):
    """Native Telegram formatting; keep report text literal, including <, &, and emoji."""
    titles = ['Сигнал клиента', 'Поворотный момент', 'Повторяющийся паттерн',
              'Главная ошибка', 'Главный удачный ход', 'Что было хорошо', 'Что надо менять', 'Что менять',
              'Фраза для следующего такого звонка', 'Диагностический вопрос',
              'Следующий шаг', 'Корень по «5 почему»',
              'Итог', 'Потребность', 'Что получилось хорошо', 'Что улучшить', 'На следующий звонок']
    headings = list(re.finditer(r'^(?:' + '|'.join(map(re.escape, titles)) + r'):', text, re.M))
    entities = []
    def add(kind, start, end):
        if end > start:
            entities.append({'type':kind, 'offset':len(text[:start].encode('utf-16-le'))//2,
                             'length':len(text[start:end].encode('utf-16-le'))//2})
    for i, match in enumerate(headings):
        add('bold', match.start(), match.end())
        if match.group() in ('Фраза для следующего такого звонка:', 'Диагностический вопрос:', 'Следующий шаг:'):
            start = match.end()
            end = headings[i+1].start() if i+1 < len(headings) else len(text)
            while start < end and text[start].isspace(): start += 1
            while end > start and text[end-1].isspace(): end -= 1
            add('blockquote', start, end)
    return sorted(entities, key=lambda e:(e['offset'], -e['length']))


def send_report(report, message_id=None):
    _, _, owner, token = settings()
    body = {'chat_id':owner,'text':report,'link_preview_options':{'is_disabled':True}}
    entities = telegram_entities(report)
    if entities:
        body['entities'] = entities
    if message_id is not None:
        body['message_id'] = message_id
    payload = json.dumps(body).encode()
    method = 'editMessageText' if message_id is not None else 'sendMessage'
    request = urllib.request.Request('https://api.telegram.org/bot'+token+'/'+method,data=payload,
                                     headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if message_id is not None:
            try:
                description = json.loads(exc.read()).get('description', '').lower()
            except (ValueError, AttributeError):
                description = ''
            if exc.code == 400 and 'message is not modified' in description:
                return message_id
            if exc.code == 400 and any(s in description for s in ('message to edit not found', "message can't be edited")):
                raise MessageUnavailable() from None
            raise RuntimeError('telegram_edit_rejected_'+str(exc.code)) from None
        if exc.code >= 500:
            raise DeliveryUnknown('telegram_server_error') from None
        raise RuntimeError('telegram_rejected_'+str(exc.code)) from None
    except (OSError, ValueError):
        if message_id is not None:
            raise RuntimeError('telegram_edit_unconfirmed') from None
        raise DeliveryUnknown('telegram_delivery_unconfirmed') from None
    message = result.get('result') if isinstance(result, dict) else None
    if not isinstance(message, dict) or not result.get('ok') or not isinstance(message.get('message_id'),int):
        if message_id is not None:
            raise RuntimeError('telegram_edit_receipt_missing')
        raise DeliveryUnknown('telegram_receipt_missing')
    if message_id is not None and result['result']['message_id'] != message_id:
        raise RuntimeError('telegram_edit_receipt_mismatch')
    return result['result']['message_id']


def process(db, row, stt=transcribe, llm=analyse, send=send_report, edit=send_report):
    job_id = row['id']
    try:
        transcript, report = row['transcript'], row['report']
        if not transcript:
            change(db, job_id, state='transcribing')
            transcript = stt(row['source'], job_id)
            change(db, job_id, transcript=transcript)
        if not report:
            change(db, job_id, state='analysing')
            report = llm(transcript, row['context'], coaching_history(db, job_id))
            change(db, job_id, report=report)
        change(db, job_id, state='delivering')
        if row['status_message_id'] is not None:
            try:
                message_id = edit(report, row['status_message_id'])
            except MessageUnavailable:
                change(db, job_id, status_message_id=None)
                message_id = send(report)
        else:
            message_id = send(report)
        change(db, job_id, state='delivered', message_id=message_id, error=None)
    except DeliveryUnknown:
        change(db, job_id, state='delivery_unknown', error='delivery_unconfirmed')
    except Exception as exc:
        attempts = row['attempts'] + 1
        # Content-free errors only: provider exception messages can contain credentials or transcripts.
        code=str(exc) if isinstance(exc,(RuntimeError,ValueError)) and re.fullmatch(r'[a-z_0-9]{1,64}',str(exc)) else type(exc).__name__
        change(db, job_id, state='failed' if attempts >= 3 else 'queued', attempts=attempts,
               due=time.time()+60*attempts, error=code)
        if attempts >= 3:
            change(db, job_id, state='notifying_failure')
            try:
                text = ('Не удалось завершить разбор записи №'+job_id[:12]+
                    ' после трёх попыток. Запись и готовые этапы сохранены. '
                    'Напиши Джарвису: «Проверь очередь разборов».')
                status_id = db.execute('SELECT status_message_id FROM jobs WHERE id=?',(job_id,)).fetchone()[0]
                if status_id is None:
                    notice = send(text)
                else:
                    try:
                        notice = edit(text, status_id)
                    except MessageUnavailable:
                        change(db, job_id, status_message_id=None)
                        notice = send(text)
                change(db,job_id,state='failed',notice_message_id=notice)
            except Exception:
                change(db,job_id,state='failed')


def recover(db):
    db.execute("UPDATE jobs SET state='queued' WHERE state IN ('transcribing','analysing')")
    db.execute("UPDATE jobs SET state='queued' WHERE state='delivering' AND status_message_id IS NOT NULL")
    db.execute("UPDATE jobs SET state='delivery_unknown',error='restart_during_delivery' WHERE state='delivering' AND status_message_id IS NULL")
    db.execute("UPDATE jobs SET state='delivery_unknown',error='status_delivery_unconfirmed' WHERE state='announcing'")
    db.execute("UPDATE jobs SET state='failed' WHERE state='notifying_failure'")
    db.commit()


def serve(db):
    import fcntl
    with (ROOT/'worker.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        recover(db)
        # ponytail: one CPU-heavy call at a time for one owner; add workers only after measured demand.
        while True:
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND due<=? ORDER BY created LIMIT 1",(time.time(),)).fetchone()
            if row:
                process(db,row)
                state=db.execute('SELECT state FROM jobs WHERE id=?',(row['id'],)).fetchone()[0]
                print(json.dumps({'id':row['id'][:12],'state':state}),flush=True)
            else:
                time.sleep(3)


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    commands=parser.add_subparsers(dest='cmd',required=True)
    add=commands.add_parser('enqueue');add.add_argument('path');add.add_argument('--context',default='')
    commands.add_parser('worker');commands.add_parser('status')
    show=commands.add_parser('show');show.add_argument('id');show.add_argument('--transcript',action='store_true')
    retry=commands.add_parser('retry');retry.add_argument('id');retry.add_argument('--confirm-resend',action='store_true')
    outcome=commands.add_parser('outcome');outcome.add_argument('status',choices=['follow_up','meeting_set','visited','sold','lost','no_contact'])
    outcome.add_argument('--id');outcome.add_argument('--message-id',type=int);outcome.add_argument('--note',default='')
    local=commands.add_parser('local-stt');local.add_argument('path');local.add_argument('output')
    args=parser.parse_args()
    with connect() as db:
        if args.cmd=='enqueue':
            print(json.dumps(enqueue(db,args.path,args.context,notify=False)))
        elif args.cmd=='worker':
            serve(db)
        elif args.cmd=='status':
            print(json.dumps([dict(r) for r in db.execute('SELECT id,state,attempts,error,message_id,status_message_id,created,updated FROM jobs ORDER BY created DESC LIMIT 20')]))
        elif args.cmd=='show':
            row=db.execute('SELECT report,transcript FROM jobs WHERE id=?',(args.id,)).fetchone()
            if not row:
                raise ValueError('job_not_found')
            print(row['transcript' if args.transcript else 'report'] or 'Результат пока не готов.')
        elif args.cmd=='local-stt':
            source=validate_input(args.path)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            text=transcribe(str(source),digest)
            output=Path(args.output)
            output.parent.mkdir(parents=True,exist_ok=True)
            output.write_text(text)
        elif args.cmd=='outcome':
            print(json.dumps(save_outcome(db,args.status,args.id,args.message_id,args.note)))
        else:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(args.id,)).fetchone()
            if not row or row['state'] not in ['failed','delivery_unknown']:
                raise ValueError('job_not_retryable')
            if row['state']=='delivery_unknown' and not args.confirm_resend:
                raise ValueError('explicit_resend_confirmation_required')
            change(db,args.id,state='queued',attempts=0,due=0,error=None)
            print('queued')


if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc,ValueError) else type(exc).__name__}))
        raise SystemExit(1)
