#!/usr/bin/env python3
"""Изолированный CPU STT. Только локально закэшированная модель, без облачного fallback."""
import json
import os
from pathlib import Path
import sys
import time
from faster_whisper import WhisperModel


def timestamp(seconds):
    millis = round(seconds * 1000)
    hours, remainder = divmod(millis, 3600000)
    minutes, remainder = divmod(remainder, 60000)
    seconds, millis = divmod(remainder, 1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{millis:03}'


def main():
    os.umask(0o077)
    source, output = sys.argv[1:]
    start = time.monotonic()
    model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=6, local_files_only=True)
    segments, info = model.transcribe(source, language='ru', beam_size=1, vad_filter=True)
    segments = list(segments)
    text = '\n'.join(s.text.strip() for s in segments if s.text.strip())
    if len(text) < 15:
        raise ValueError('no_clear_speech')
    Path(output+'.txt').write_text(text)
    Path(output+'.srt').write_text('\n\n'.join(
        f'{i}\n{timestamp(s.start)} --> {timestamp(s.end)}\n{s.text.strip()}' for i,s in enumerate(segments,1)))
    print(json.dumps({'model':'small-int8','duration':info.duration,'seconds':round(time.monotonic()-start,2)}))


if __name__ == '__main__':
    main()
