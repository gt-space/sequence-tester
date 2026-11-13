"""Keep upstream synchronization PRs reviewable; no merge operation is provided."""
import json
import subprocess

def gh(*args):
    return subprocess.check_output(['gh',*args],text=True)

def ensure_draft(run=gh):
    branch='automation/luna-api-drift'
    existing=json.loads(run('pr','list','--head',branch,'--base','main','--state','open','--json','number'))
    if not existing:
        run('pr','create','--draft','--base','main','--head',branch,'--title','chore: review upstream Luna API drift','--body','Downstream contract update. DO NOT MERGE until implementation review, independent binding tests and CI pass. Luna is read only.')
    elif not json.loads(run('pr','view',branch,'--json','isDraft'))['isDraft']:
        run('pr','ready',branch,'--undo')
if __name__=='__main__':ensure_draft()
