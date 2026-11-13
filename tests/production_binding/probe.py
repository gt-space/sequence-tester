"""Entry point reachable only in the minimal private filesystem namespace."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

host=json.loads(os.environ['AUDIT_HOST_NAMESPACES'])
ns={name:os.readlink('/proc/self/ns/'+name) for name in host}
assert all(ns[name]!=host[name] for name in ns), (ns,host)
assert not Path(os.environ['AUDIT_HOST_SENTINEL']).exists()
assert not Path('/home').exists()
assert not Path('/dev/gpiomem').exists()
assert list(Path('/dev/shm').iterdir())==[]
assert not Path('/tmp/fc_sam_commands').exists()
assert os.listdir('/sys/class/net')==[] if Path('/sys/class/net').exists() else True
# Only after all isolation assertions may production paths be used.
sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
sock.bind('/tmp/fc_sam_commands');sock.settimeout(2)
fixture='/build/luna-synthetic-fixture'
def write(value,unit):subprocess.run([fixture,str(value),unit],check=True,stdout=subprocess.DEVNULL)
write(0,'psi')
shutil.copyfile('/build/libcommon.so','/tmp/common.so')
import common
from engine import Simulator
rows=[]
for unit in ['psi','unknown','V']:
    for value in [0,299,300,301,400]:
        write(value,unit)
        sim=Simulator({'valve':'CLOSED'},{'FTPT':{'unit':unit,'samples':[{'at':0,'value':value}],'interpolation':'step'}}).make_module()
        for operator in ['<','<=','==','!=','>','>=']:
            for template in ['sensor OP threshold','threshold OP sensor','sensor.read() OP threshold','threshold OP sensor.read()']:
                expression=template.replace('OP',operator)
                def outcome(env):
                    try:return eval(expression,env)
                    except BaseException as error:return type(error).__name__
                real=outcome({'sensor':common.Sensor('FTPT'),'threshold':300*common.psi})
                modeled=outcome({'sensor':sim.Sensor('FTPT'),'threshold':300*sim.psi})
                assert real==modeled,(unit,value,expression,real,modeled)
                rows.append([unit,value,expression,real])
errors={}
for expr in ['common.Sensor("missing").read()','common.Valve("missing").is_open()','common.Sensor("FTPT").read(1)','common.Sensor("FTPT").open()','common.wait_for(500)','common.wait_for()','common.Valve("valve").open(True)','common.Valve("valve").actuate("OPEN")']:
    try:eval(expr);raise AssertionError('Unexpected pass: '+expr)
    except Exception as error:errors[expr]=type(error).__name__
assert errors['common.Sensor("missing").read()']=='SensorNotFoundError'
assert errors['common.Valve("missing").is_open()']=='ValveNotFoundError'
assert common.Valve('valve').is_open() is True
write(400,'psi')
common.wait_until(lambda: common.Sensor('FTPT').read()>300*common.psi,5*common.s)
commands=[]
for call in [lambda:common.Valve('valve').open(),lambda:common.Valve('valve').actuate(open=False),lambda:common.create_abort_stage('synthetic','False',{common.Valve('valve'):(common.ValveState.Closed,500)}),lambda:common.set_abort_stage('synthetic')]:
    call();data=sock.recv(4096)
    decoded=subprocess.run([fixture,'decode'],input=data,capture_output=True,check=True)
    commands.append(json.loads(decoded.stdout))
assert commands[0]=={'ActuateValve':{'valve':'valve','state':'open'}},commands
assert commands[1]=={'ActuateValve':{'valve':'valve','state':'closed'}},commands
print(json.dumps({'isolation':{'namespaces':ns,'host_namespaces':host,'private_tmp_shm':True,'host_sentinel_inaccessible':True},'comparisons':len(rows),'errors':errors,'commands':commands,'library':'unmodified common, production read/deserialization/IPC paths','observations':rows}))
