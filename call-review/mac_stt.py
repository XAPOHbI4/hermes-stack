"""VPS client for the existing private SSH route to the owner's Mac."""
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

VERSION = 'mac-turbo-vad-v1'
SSH = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
       'mac-mini-jarvis', '/usr/bin/python3', '/Users/mac_mini/.jarvis-stt/mac_runner.py']


def timestamp(seconds):
    millis = round(seconds * 1000)
    hours, rest = divmod(millis, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, millis = divmod(rest, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def render(data, digest):
    if data.get('id') != digest or data.get('version') != VERSION:
        raise ValueError('mac_result_identity_invalid')
    duration = data.get('duration')
    if not isinstance(duration, (int, float)) or not 1 <= duration <= 3600:
        raise ValueError('mac_duration_invalid')
    segments = data.get('segments')
    if not isinstance(segments, list) or not 1 <= len(segments) <= 10000:
        raise ValueError('mac_segments_invalid')
    lines, subtitles, chars = [], [], 0
    previous = 0
    for i, s in enumerate(segments, 1):
        start, end, text = s.get('start'), s.get('end'), s.get('text')
        if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)):
            raise ValueError('mac_timestamps_invalid')
        if not 0 <= start <= end <= duration + 1 or start < previous:
            raise ValueError('mac_timestamps_invalid')
        previous = start
        if not isinstance(text, str) or not text.strip():
            raise ValueError('mac_text_invalid')
        chars += len(text)
        channel = s.get('channel')
        if channel not in ('0', '1', '?'):
            raise ValueError('mac_channel_invalid')
        label = {'0':'Канал 1', '1':'Канал 2', '?':'Говорящий не определён'}[channel]
        lines.append(f'[{timestamp(start)} — {timestamp(end)}] {label}: {text}')
        subtitles.append(f'{i}\n{timestamp(start)} --> {timestamp(end)}\n{label}: {text}')
    if not 15 <= chars <= 120000:
        raise ValueError('transcript_length_invalid')
    note = ('Метки каналов — оценка по стереосигналу, не идентификация людей. '
            'Один канал может содержать оператора и менеджера; смешанные реплики могут быть размечены ошибочно.'
            if data.get('speaker_method') == 'stereo_energy' else
            'Говорящие по этой записи не разделены.')
    return note + '\n\n' + '\n'.join(lines), '\n\n'.join(subtitles)


def transcribe(source, digest, root):
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('invalid_audio_id')
    folder = Path(root) / 'transcripts' / VERSION
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    cache = folder / (digest + '.json')
    started = time.monotonic()
    if cache.is_file():
        data = json.loads(cache.read_text(encoding='utf-8'))
    else:
        try:
            with open(source, 'rb') as audio:
                result = subprocess.run([*SSH, digest], stdin=audio, capture_output=True, timeout=1950)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('mac_unavailable_or_timeout') from None
        if result.returncode:
            raise RuntimeError('mac_stt_failed_or_unavailable')
        if len(result.stdout) > 2 * 1024**2:
            raise ValueError('mac_response_too_large')
        data = json.loads(result.stdout)
    text, srt = render(data, digest)
    # JSON is the commit marker, written last; older CPU transcripts are never reused.
    for suffix, content in [('.txt', text), ('.srt', srt), ('.json', json.dumps(data, ensure_ascii=False))]:
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as saved:
            saved.write(content.encode()); saved.flush(); os.fsync(saved.fileno())
        os.replace(saved.name, folder / (digest + suffix))
    print(json.dumps({'stage':'stt', 'backend':'mac', 'id':digest[:12],
                      'seconds':round(time.monotonic()-started, 2)}), flush=True)
    return text
