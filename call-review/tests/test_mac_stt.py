import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('mac_stt', Path(__file__).parents[1] / 'mac_stt.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class MacSTTTest(unittest.TestCase):
    def setUp(self):
        self.digest = 'a' * 64
        self.data = dict(id=self.digest, version=m.VERSION, duration=20,
                         speaker_method='stereo_energy',
                         segments=[dict(start=1, end=4, channel='0', text='Подскажите, когда удобно приехать?'),
                                   dict(start=5, end=8, channel='1', text='В пятницу после обеда.')])

    def test_time_and_channel_labels_without_invented_roles(self):
        text, srt = m.render(self.data, self.digest)
        self.assertIn('Канал 1:', text)
        self.assertIn('Канал 2:', text)
        self.assertNotIn('Василий:', text)
        self.assertIn('00:00:01,000 --> 00:00:04,000', srt)
        for key, value in [('id', 'b'*64), ('version', 'old')]:
            bad = copy.deepcopy(self.data); bad[key] = value
            with self.assertRaises(ValueError): m.render(bad, self.digest)
        for value in [-1, float('nan'), 50]:
            bad = copy.deepcopy(self.data); bad['segments'][0]['start'] = value
            with self.assertRaises(ValueError): m.render(bad, self.digest)

    def test_cpu_cache_not_reused_mac_cache_survives_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'transcripts').mkdir()
            (root/'transcripts'/(self.digest+'.txt')).write_text('OLD CPU TRANSCRIPT')
            source = root/'audio'; source.write_bytes(b'test')
            result = subprocess.CompletedProcess([], 0, json.dumps(self.data).encode(), b'')
            with patch.object(m.subprocess, 'run', return_value=result) as run:
                first = m.transcribe(source, self.digest, root)
                run.assert_called_once()
            with patch.object(m.subprocess, 'run', side_effect=AssertionError('must use cache')):
                self.assertEqual(first, m.transcribe(source, self.digest, root))
            self.assertEqual((root/'transcripts'/(self.digest+'.txt')).read_text(), 'OLD CPU TRANSCRIPT')

    def test_ssh_failure_leaves_no_success_cache_and_does_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = root/'audio'; source.write_bytes(b'test')
            result = subprocess.CompletedProcess([], 255, b'', b'PRIVATE SSH DETAILS')
            with patch.object(m.subprocess, 'run', return_value=result):
                with self.assertRaisesRegex(RuntimeError, '^mac_stt_failed_or_unavailable$'):
                    m.transcribe(source, self.digest, root)
            self.assertFalse(list(root.rglob('*.json')))
            with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ssh', 1950)):
                with self.assertRaisesRegex(RuntimeError, '^mac_unavailable_or_timeout$'):
                    m.transcribe(source, self.digest, root)


if __name__ == '__main__':
    unittest.main()
