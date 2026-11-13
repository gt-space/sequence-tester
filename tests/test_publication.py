"""Real Git publication against disposable bare repos; scripted gh lifecycle."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
def git(cwd,*args):
    return subprocess.check_output(['git','-C',str(cwd),*args],text=True).strip()
class Publication(unittest.TestCase):
    def test_status_publication_preserves_main_and_reports_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);remote=root/'remote.git';work=root/'work'
            subprocess.run(['git','init','--bare',str(remote)],check=True,capture_output=True)
            subprocess.run(['git','clone',str(remote),str(work)],check=True,capture_output=True)
            git(work,'config','user.name','Audit');git(work,'config','user.email','audit@example.invalid')
            (work/'README').write_text('synthetic main')
            git(work,'add','.');git(work,'commit','-m','base');git(work,'branch','-M','main');git(work,'push','origin','main')
            before=git(remote,'rev-parse','main')
            status=root/'status.json'
            for compatible in [True,False]:
                status.write_text(json.dumps({'schema_version':1,'mode':'live','luna_sha':'a'*40,'tester_sha':'b'*40,'compatible':compatible,'checked_at':'2026-11-13T00:00:00Z','error':''}))
                subprocess.run([sys.executable,str(ROOT/'scripts/publish_luna_status.py'),'--remote',str(remote),'--status',str(status)],check=True,capture_output=True)
                self.assertEqual(json.loads(git(remote,'show','compatibility-status:status.json'))['compatible'],compatible)
                self.assertEqual(git(remote,'rev-parse','main'),before)
            failure=subprocess.run([sys.executable,str(ROOT/'scripts/publish_luna_status.py'),'--remote',str(root/'absent.git'),'--status',str(status)],capture_output=True)
            self.assertNotEqual(failure.returncode,0)
    def test_bot_creates_or_returns_pr_to_draft(self):
        spec=importlib.util.spec_from_file_location('bot',ROOT/'scripts/luna_bot.py');bot=importlib.util.module_from_spec(spec);spec.loader.exec_module(bot)
        class FakeGithub:
            def __init__(self,existing,draft):self.existing=existing;self.draft=draft;self.calls=[]
            def __call__(self,*args):
                self.calls.append(args)
                if args[:2]==('pr','list'):return json.dumps([{'number':42}] if self.existing else [])
                if args[:2]==('pr','view'):return json.dumps({'isDraft':self.draft})
                return ''
        for exists,draft in [(False,False),(True,False),(True,True)]:
            fake=FakeGithub(exists,draft);bot.ensure_draft(fake)
            calls=fake.calls
            self.assertFalse(any('merge' in call for call in calls))
            if not exists:self.assertTrue(any(call[:2]==('pr','create') and '--draft' in call for call in calls))
            elif not draft:self.assertIn(('pr','ready','automation/luna-api-drift','--undo'),calls)
            else:self.assertEqual(len(calls),2)
