"""Build unchanged common in a disposable copy; execute ONLY inside bubblewrap.

Usage: python3 scripts/test_production_binding.py UPSTREAM_ARCHIVE OUTPUT_DIR
Fail closed if namespaces/private filesystems are unavailable. Never imports
common in the host process. No host /tmp, /dev/shm, /home or service sockets
are mounted into the test namespace.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if not shutil.which('bwrap'):raise SystemExit('BLOCKED: bubblewrap unavailable; no IPC test executed')
    # Probe all namespaces before building or importing production code.
    subprocess.run(['bwrap','--unshare-all','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','/usr/bin/true'],check=True)
    with tempfile.TemporaryDirectory(prefix='luna-production-') as tmp:
        work=Path(tmp)
        upstream=work/'upstream';shutil.copytree(args.source,upstream)
        # Compare original common byte-for-byte before and after the build.
        def hashes():
            import hashlib
            return {str(p.relative_to(upstream/'common')):hashlib.sha256(p.read_bytes()).hexdigest() for p in (upstream/'common').rglob('*') if p.is_file()}
        before=hashes()
        target=work/'target'
        env={**os.environ,'CARGO_TARGET_DIR':str(target)}
        subprocess.run(['cargo','build','--locked','--manifest-path',str(upstream/'Cargo.toml'),'-p','common','--features','sequences'],env=env,check=True)
        fixture=work/'fixture';(fixture/'src').mkdir(parents=True)
        (fixture/'src/main.rs').write_bytes((ROOT/'tests/production_binding/fixture.rs').read_bytes())
        (fixture/'Cargo.toml').write_text('[package]\nname="luna-synthetic-fixture"\nversion="0.1.0"\nedition="2021"\n[workspace]\n[dependencies]\ncommon={path='+json.dumps(str(upstream/'common'))+'}\nmmap-sync="=2.0.1"\npostcard="1"\nserde_json="1"\n')
        shutil.copyfile(upstream/'Cargo.lock',fixture/'Cargo.lock')
        subprocess.run(['cargo','build','--manifest-path',str(fixture/'Cargo.toml')],env=env,check=True)
        if before!=hashes():raise SystemExit('FAIL: build changed common source')
        # A host sentinel and namespace IDs provide independently checked negatives.
        sentinel=work/'HOST_SENTINEL';sentinel.write_text('must not be visible')
        namespaces={name:os.readlink('/proc/self/ns/'+name) for name in ['mnt','ipc','net','pid']}
        cmd=['bwrap','--unshare-all','--die-with-parent','--new-session','--ro-bind','/usr','/usr','--ro-bind','/lib','/lib','--ro-bind','/lib64','/lib64','--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/dev/shm','--tmpfs','/dev/shm','--ro-bind',str(target/'debug'),'/build','--ro-bind',str(ROOT/'tests/production_binding'),'/tests','--ro-bind',str(ROOT/'src'),'/tester','--clearenv','--setenv','PATH','/usr/bin:/bin','--setenv','PYTHONPATH','/tmp:/tester','--setenv','AUDIT_HOST_NAMESPACES',json.dumps(namespaces),'--setenv','AUDIT_HOST_SENTINEL',str(sentinel),'/usr/bin/python3','/tests/probe.py']
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=120)
        (output/'production-binding.stdout').write_text(result.stdout)
        (output/'production-binding.stderr').write_text(result.stderr)
        if result.returncode:raise SystemExit('FAIL production probe: '+result.stderr[-3000:])
        payload=json.loads(result.stdout.splitlines()[-1])
        payload['common_source_unchanged']=True
        (output/'production-binding.json').write_text(json.dumps(payload,indent=2)+'\n')
        print(json.dumps(payload))
if __name__=='__main__':main()
