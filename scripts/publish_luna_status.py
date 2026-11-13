"""Publish only compatibility-status using an isolated Git checkout and a lease."""
import argparse
import json
import os
import base64
from pathlib import Path
import subprocess
import tempfile
from write_luna_status import build_status

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remote',required=True)
    parser.add_argument('--status',type=Path,required=True)
    args=parser.parse_args()
    payload=json.loads(args.status.read_text())
    if payload.get('mode')!='live' or payload.get('schema_version')!=1 or type(payload.get('compatible')) is not bool:
        raise ValueError('Expected a versioned live status with explicit boolean compatibility')
    build_status('live',payload['luna_sha'],payload['tester_sha'],payload['compatible'])
    # remote may be an authenticated remote URL or a local bare test repository.
    branch='refs/heads/compatibility-status'
    env=os.environ.copy()
    if args.remote.startswith("https://github.com/") and env.get("GH_TOKEN"):
        # checkout's local http.extraheader is not inherited by the isolated repo.
        # Pass credentials via environment, never in remote URLs or logs.
        env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.https://github.com/.extraheader",
                   GIT_CONFIG_VALUE_0="AUTHORIZATION: basic " + base64.b64encode(("x-access-token:"+env["GH_TOKEN"]).encode()).decode())
    old=subprocess.check_output(['git','ls-remote',args.remote,branch],text=True,env=env).strip()
    expected=old.split()[0] if old else ''
    with tempfile.TemporaryDirectory(prefix='luna-status-') as tmp:
        def git(*params):subprocess.run(['git','-C',tmp,*params],check=True,env=env)
        git('init');git('config','user.name','github-actions[bot]');git('config','user.email','41898282+github-actions[bot]@users.noreply.github.com')
        (Path(tmp)/'status.json').write_text(json.dumps(payload,indent=2)+'\n')
        git('add','status.json');git('commit','-m','Refresh Luna API compatibility status')
        git('push','--force-with-lease='+branch+':'+expected,args.remote,'HEAD:'+branch)
if __name__=='__main__':main()
