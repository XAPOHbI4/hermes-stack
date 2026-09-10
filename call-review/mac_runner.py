#!/usr/bin/env python3
"""SSH-only Mac worker: audio on stdin, cached JSON on stdout. No network API."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path.home() / '.jarvis-stt'
VERSION = 'mac-turbo-vad-v1'
MODEL = Path.home() / '.sales-assistant-worker/models/ggml-large-v3-turbo-q5_0.bin'


def run(args, timeout=900):
    result = subprocess.run(args, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('mac_media_process_failed')
    return result.stdout


def main():
    os.umask(0o077)
    digest = sys.argv[1]
    if not re.fullmatch('[a-f0-9]{64}', digest):
        raise ValueError('invalid_audio_id')
    ROOT.mkdir(mode=0o700, exist_ok=True)
    folder = ROOT / VERSION
    folder.mkdir(mode=0o700, exist_ok=True)
    started = time.monotonic()
    # ponytail: one Mac job at a time; a single owner does not need another queue.
    with (ROOT / 'runner.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        audio = sys.stdin.buffer.read(100 * 1024**2 + 1)
        if not 0 < len(audio) <= 100 * 1024**2 or hashlib.sha256(audio).hexdigest() != digest:
            raise ValueError('audio_integrity_failed')
        cache = folder / (digest + '.json')
        if cache.is_file():
            print(cache.read_text(encoding='utf-8'))
            return
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            source, wav, output = (Path(tmp) / name for name in ('source.audio', 'audio.wav', 'result'))
            source.write_bytes(audio)
            probe = json.loads(run(['/opt/homebrew/bin/ffprobe', '-v', 'error',
                '-protocol_whitelist', 'file,pipe', '-show_entries',
                'format=duration:stream=codec_type,channels', '-of', 'json', str(source)], 30))
            duration = float(probe.get('format', {}).get('duration', 0))
            streams = [s for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
            if not 1 <= duration <= 3600 or not streams:
                raise ValueError('audio_duration_or_format')
            stereo = streams[0].get('channels') == 2
            run(['/opt/homebrew/bin/ffmpeg', '-nostdin', '-y', '-v', 'error',
                 '-protocol_whitelist', 'file,pipe', '-i', str(source), '-ar', '16000',
                 '-ac', '2' if stereo else '1', '-c:a', 'pcm_s16le', str(wav)], 180)
            args = ['/opt/homebrew/bin/whisper-cli', '-m', str(MODEL), '-f', str(wav),
                    '-l', 'ru', '--vad', '-vm', str(ROOT / 'ggml-silero-v6.2.0.bin'),
                    '-oj', '-of', str(output)]
            if stereo:
                args.append('-di')
            run(args, 1800)
            raw = json.loads(output.with_suffix('.json').read_text(encoding='utf-8'))
            segments = [{'start':s['offsets']['from'] / 1000,
                         'end':s['offsets']['to'] / 1000,
                         'text':s['text'].strip(),
                         'channel':s.get('speaker', '?') if stereo else '?'}
                        for s in raw['transcription'] if s['text'].strip()]
            result = {'id':digest, 'version':VERSION, 'duration':duration,
                      'seconds':round(time.monotonic()-started, 2),
                      'speaker_method':'stereo_energy' if stereo else 'unknown',
                      'segments':segments}
            encoded = json.dumps(result, ensure_ascii=False)
            with tempfile.NamedTemporaryFile(dir=folder, delete=False) as saved:
                saved.write(encoded.encode()); saved.flush(); os.fsync(saved.fileno())
            os.replace(saved.name, cache)
            print(encoded)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # No provider stderr, audio, transcript, or connection secrets in error output.
        code = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__
        print(json.dumps({'error':code if re.fullmatch('[A-Za-z_0-9]{1,64}',code) else 'mac_stt_failed'}))
        sys.exit(1)
