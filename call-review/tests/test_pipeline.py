import importlib.util
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('pipeline', Path(__file__).parents[1] / 'pipeline.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_root, self.old_allowed = p.ROOT, p.ALLOWED
        p.ROOT, p.ALLOWED = self.root/'runtime', [self.root/'cache']
        p.ALLOWED[0].mkdir()
        self.audio = p.ALLOWED[0]/'call.m4a'
        self.audio.write_bytes(b'synthetic audio stand-in')
        self.db = p.connect()

    def tearDown(self):
        self.db.close()
        p.ROOT, p.ALLOWED = self.old_root, self.old_allowed
        self.tmp.cleanup()

    def add(self):
        with patch.object(p, 'probe', return_value=10):
            return p.enqueue(self.db,self.audio)['id']

    def row(self, job_id):
        return self.db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()

    def test_duplicate_input_and_path_boundary(self):
        first=self.add()
        self.assertEqual(first,self.add())
        self.assertEqual(self.db.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
        outside=self.root/'secret.txt';outside.write_text('not audio')
        with self.assertRaisesRegex(ValueError,'only_telegram'):
            p.enqueue(self.db,outside)
        self.assertTrue(Path(self.row(first)['source']).is_file())

    def test_restart_retains_transcript_and_retries_only_missing_stage(self):
        job=self.add()
        def fail_llm(*args):raise RuntimeError('temporary')
        p.process(self.db,self.row(job),stt=lambda *a:'Подтверждённый транскрипт',llm=fail_llm)
        self.assertEqual(self.row(job)['state'],'queued')
        p.change(self.db,job,state='analysing')
        p.recover(self.db)
        def no_stt(*args):self.fail('STT repeated after persisted transcript')
        p.process(self.db,self.row(job),stt=no_stt,llm=lambda *a:'Отчёт',send=lambda r:123)
        self.assertEqual(self.row(job)['state'],'delivered')
        self.assertEqual(self.row(job)['message_id'],123)

    def test_delivery_failure_never_claims_success_or_reanalyses(self):
        job=self.add()
        def reject(*args):raise RuntimeError('telegram_rejected_429')
        p.process(self.db,self.row(job),stt=lambda *a:'Текст',llm=lambda *a:'Разбор',send=reject)
        self.assertEqual(self.row(job)['state'],'queued')
        self.assertIsNone(self.row(job)['message_id'])
        def no_llm(*args):self.fail('Already saved report was regenerated')
        p.process(self.db,self.row(job),llm=no_llm,send=lambda r:124)
        self.assertEqual(self.row(job)['message_id'],124)

    def test_ambiguous_delivery_and_restart_require_manual_reconciliation(self):
        job=self.add()
        def ambiguous(*args):raise p.DeliveryUnknown()
        p.process(self.db,self.row(job),stt=lambda *a:'Текст',llm=lambda *a:'Разбор',send=ambiguous)
        self.assertEqual(self.row(job)['state'],'delivery_unknown')
        p.recover(self.db)
        self.assertEqual(self.row(job)['state'],'delivery_unknown')
        p.change(self.db,job,state='delivering')
        p.recover(self.db)
        self.assertEqual(self.row(job)['state'],'delivery_unknown')

    def test_retry_exhaustion_preserves_source_and_safe_error(self):
        job=self.add()
        def broken(*args):raise RuntimeError('TOKEN_secret CLIENT_full_transcript')
        for _ in range(3):p.process(self.db,self.row(job),stt=broken,send=lambda text:999)
        row=self.row(job)
        self.assertEqual(row['state'],'failed')
        self.assertEqual(row['attempts'],3)
        self.assertEqual(row['error'],'RuntimeError')
        self.assertEqual(row['notice_message_id'],999)
        self.assertTrue(Path(row['source']).is_file())

    def test_report_rejects_fabricated_quotes_and_allows_no_errors(self):
        data=dict(opening='Василий, удалось согласовать время.',client_signal='Клиент сам назвал удобное время.',
            turning_point='Менеджер закрепил точный контакт.',trend='',
            main_point_title='Главный удачный ход',main_point='Удобство клиента учтено.',
            better_phrase='Сейчас удобно говорить?',diagnostic_question='Когда удобно перезвонить?',
            next_step='В 18:30',root_cause='Закрепить конкретную договорённость.',
            strengths=[dict(observation='Уточнил удобное время',quote='Когда можно перезвонить?')],improvements=[])
        text='Менеджер: Когда можно перезвонить? Клиент: После шести.'
        report=p.render(data,text)
        self.assertIn('Явных ошибок',report)
        self.assertTrue(report.startswith('Василий,'))
        self.assertIn('Диагностический вопрос:\nКогда удобно перезвонить?',report)
        self.assertIn('Главный удачный ход:',report)
        self.assertIn('Сигнал клиента:',report)
        self.assertIn('Поворотный момент:',report)
        self.assertNotIn('Повторяющийся паттерн:',report)
        self.assertIn('Корень по «5 почему»:',report)
        self.assertNotIn('«Когда можно перезвонить?»',report)
        self.assertNotIn('Ограничения:',report)
        self.assertNotIn('автоматической расшифровке',report)
        self.assertNotIn('учебном дневнике',report)
        missing=data.copy();del missing['diagnostic_question']
        with self.assertRaisesRegex(ValueError,'invalid_report_field'):p.render(missing,text)
        data['strengths'][0]['quote']='Мы точно продадим вам автомобиль за миллион'
        with self.assertRaisesRegex(ValueError,'quote_not_in_transcript'):p.render(data,text)

    def test_previous_reviews_and_real_outcome_reach_next_analysis(self):
        first=self.add();p.change(self.db,first,state='delivered',report='Первый разбор',message_id=901)
        p.save_outcome(self.db,'visited',message_id=901,note='Клиент приехал')
        self.audio.write_bytes(b'second call');second=self.add()
        p.change(self.db,second,state='delivered',report='Второй разбор',message_id=902)
        self.audio.write_bytes(b'third call');third=self.add()
        history=p.coaching_history(self.db,third)
        self.assertEqual([x['report'] for x in history],['Первый разбор','Второй разбор'])
        self.assertEqual(history[0]['outcome'],'visited')
        self.assertEqual(history[0]['outcome_note'],'Клиент приехал')
        captured=[]
        p.process(self.db,self.row(third),stt=lambda *a:'Текст',
                  llm=lambda transcript,context,previous:(captured.extend(previous) or 'Третий разбор'),
                  send=lambda text:903)
        self.assertEqual(len(captured),2)
        self.assertEqual(self.row(third)['message_id'],903)

    def test_two_jobs_edit_their_own_placeholders_and_duplicate_sends_nothing(self):
        with patch.object(p,'probe',return_value=10), patch.object(p,'send_report',side_effect=[701,702]) as announce:
            first=p.enqueue(self.db,self.audio,notify=True)
            self.assertEqual(p.enqueue(self.db,self.audio,notify=True),first)
            self.audio.write_bytes(b'another recording')
            second=p.enqueue(self.db,self.audio,notify=True)
            self.assertEqual(announce.call_count,2)
        edits=[]
        def edit(text,mid):edits.append(mid);return mid
        def no_send(*args):self.fail('must edit, not send')
        for job in [second,first]:
            p.process(self.db,self.row(job['id']),stt=lambda *a:'transcript',llm=lambda *a:'report',send=no_send,edit=edit)
            self.assertEqual(self.row(job['id'])['message_id'],job['status_message_id'])
        self.assertEqual(edits,[702,701])

    def test_edit_failure_and_restart_retry_without_regenerating_report(self):
        job=self.add();p.change(self.db,job,status_message_id=703)
        def fail(*args):raise RuntimeError('telegram_edit_unconfirmed')
        p.process(self.db,self.row(job),stt=lambda *a:'transcript',llm=lambda *a:'report',edit=fail)
        self.assertEqual(self.row(job)['state'],'queued')
        self.assertEqual(self.row(job)['report'],'report')
        p.change(self.db,job,state='delivering');p.recover(self.db)
        self.assertEqual(self.row(job)['state'],'queued')
        def no_work(*args):self.fail('completed work repeated')
        p.process(self.db,self.row(job),stt=no_work,llm=no_work,send=no_work,edit=lambda text,mid:mid)
        self.assertEqual(self.row(job)['message_id'],703)

    def test_unknown_placeholder_delivery_is_not_automatically_repeated(self):
        with patch.object(p,'probe',return_value=10), patch.object(p,'send_report',side_effect=p.DeliveryUnknown()) as announce:
            job=p.enqueue(self.db,self.audio,notify=True)
            self.assertEqual(job['state'],'delivery_unknown')
            p.enqueue(self.db,self.audio,notify=True)
            announce.assert_called_once()
        p.change(self.db,job['id'],state='announcing');p.recover(self.db)
        self.assertEqual(self.row(job['id'])['state'],'delivery_unknown')

    def test_deleted_placeholder_gets_one_new_report(self):
        job=self.add();p.change(self.db,job,status_message_id=704)
        def deleted(*args):raise p.MessageUnavailable()
        sent=[]
        def send(text):sent.append(text);return 705
        p.process(self.db,self.row(job),stt=lambda *a:'transcript',llm=lambda *a:'report',edit=deleted,send=send)
        self.assertEqual(sent,['report'])
        self.assertIsNone(self.row(job)['status_message_id'])
        self.assertEqual(self.row(job)['message_id'],705)

    def test_telegram_edit_is_idempotent_but_new_send_is_not(self):
        def error(description):
            return urllib.error.HTTPError('https://example.invalid',400,'bad',{},io.BytesIO(json.dumps({'description':description}).encode()))
        with patch.object(p,'settings',return_value=({},'key','123','token')):
            with patch.object(p.urllib.request,'urlopen',side_effect=error('Bad Request: message is not modified')):
                self.assertEqual(p.send_report('report',706),706)
            with patch.object(p.urllib.request,'urlopen',side_effect=error('Bad Request: message to edit not found')):
                with self.assertRaises(p.MessageUnavailable):p.send_report('report',706)
            with patch.object(p.urllib.request,'urlopen',side_effect=OSError('private')):
                with self.assertRaisesRegex(RuntimeError,'telegram_edit_unconfirmed'):p.send_report('report',706)
                with self.assertRaises(p.DeliveryUnknown):p.send_report('report')

    def test_telegram_formatting_preserves_literals_and_utf16_offsets_on_send_and_edit(self):
        text='Василий, 🚗 цена < 4 млн & условия.\n\nГлавная ошибка: спор о цене.\n\nФраза для следующего такого звонка:\nСравним A & B?\n\nДиагностический вопрос:\nЧто для вас важно?\n\nСледующий шаг:\nПодтвердить время.\n\nКорень по «5 почему»: привычка защищать цену.'
        entities=p.telegram_entities(text)
        raw=text.encode('utf-16-le')
        formatted=[(e['type'],raw[e['offset']*2:(e['offset']+e['length'])*2].decode('utf-16-le')) for e in entities]
        self.assertIn(('bold','Фраза для следующего такого звонка:'),formatted)
        self.assertIn(('bold','Главная ошибка:'),formatted)
        self.assertEqual([value for kind,value in formatted if kind=='blockquote'],
                         ['Сравним A & B?','Что для вас важно?','Подтвердить время.'])
        self.assertEqual(p.telegram_entities('Запись принята в очередь.'),[])
        payloads=[]
        def respond(request,timeout):
            payloads.append(json.loads(request.data))
            return io.BytesIO(json.dumps({'ok':True,'result':{'message_id':801}}).encode())
        with patch.object(p,'settings',return_value=({},'key','123','token')),patch.object(p.urllib.request,'urlopen',side_effect=respond):
            p.send_report(text)
            p.send_report(text,801)
        for payload in payloads:
            self.assertEqual(payload['text'],text)
            self.assertEqual(payload['entities'],entities)
            self.assertNotIn('parse_mode',payload)


if __name__=='__main__':unittest.main()
