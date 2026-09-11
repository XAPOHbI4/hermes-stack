import contextlib, importlib.util, io, json, os, tempfile, unittest
from pathlib import Path

TMP=tempfile.TemporaryDirectory(); ROOT=Path(TMP.name)
(ROOT/'references').mkdir(); (ROOT/'references'/'lessons').mkdir()
items=[]
for i in range(10):
    ident=f'{i+1:02}-lesson'; card=f'references/lessons/{ident}.md'
    (ROOT/card).write_text(f'# Lesson {i+1}',encoding='utf-8')
    items.append({'id':ident,'title':f'Урок {i+1}','interval_days':3 if i<7 else 2,'card':card,'subtitles':card})
(ROOT/'references'/'manifest.json').write_text(json.dumps({'lessons':items}),encoding='utf-8')
os.environ['CONSTANTS_COURSE_ROOT']=str(ROOT)
os.environ['CONSTANTS_COURSE_DB']=str(ROOT/'state.sqlite3')
spec=importlib.util.spec_from_file_location('course',Path(__file__).parents[1]/'scripts'/'course.py')
course=importlib.util.module_from_spec(spec); spec.loader.exec_module(course)

class Args: pass
def call(fn,args=None):
    out=io.StringIO()
    db=course.connect()
    try:
        with contextlib.redirect_stdout(out): fn(db,args or Args())
    finally:
        db.close()
    return json.loads(out.getvalue())

class CourseTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop('CONSTANTS_COURSE_INTERVAL_DAYS',None)
        p=Path(os.environ['CONSTANTS_COURSE_DB'])
        if p.exists(): p.unlink()
    def test_title_discussion_homework_and_wait(self):
        self.assertEqual(call(course.cmd_start)['message'],'Урок 1')
        self.assertEqual(call(course.cmd_watched)['action'],'discussion')
        a=Args(); a.kind='reflection'; a.text='Мой вывод'; self.assertTrue(call(course.cmd_record,a)['ok'])
        a.phase='homework'; call(course.cmd_phase,a)
        self.assertEqual(call(course.cmd_complete)['action'],'waiting')
        self.assertEqual(call(course.cmd_resume)['action'],'waiting')
    def test_all_lessons_can_complete(self):
        os.environ['CONSTANTS_COURSE_INTERVAL_DAYS']='0'; call(course.cmd_start)
        for _ in range(10): call(course.cmd_watched); result=call(course.cmd_complete)
        self.assertEqual(result['action'],'complete')
        self.assertEqual(call(course.cmd_status)['completed'],10)
    def test_pause_is_silent_for_reminders(self):
        call(course.cmd_start); call(course.cmd_pause)
        a=Args(); a.after_hours=0; a.cooldown_hours=0; out=io.StringIO()
        db=course.connect()
        try:
            with contextlib.redirect_stdout(out): course.cmd_reminder(db,a)
        finally:
            db.close()
        self.assertEqual(out.getvalue().strip(),'NO_REPLY')

if __name__=='__main__': unittest.main()
