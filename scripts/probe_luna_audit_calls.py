"""Compare safe calls to extracted bindings; Valve actuation/state are STUBS."""
import json
from pathlib import Path
import sys
sys.path[:0]=[sys.argv[1],str(Path(__file__).resolve().parents[1]/'src')]
import luna_probe as real
from engine import Simulator
sim=Simulator({'valve':'CLOSED'},{'FTPT':{'unit':'psi','samples':[{'at':0,'value':400}],'interpolation':'step'}}).make_module()
real_env={name:getattr(real,name) for name in ['wait_for','wait_until','interval','Pressure','Valve','ValveState']}
real_env.update(psi=real.Pressure(1),ms=real.Duration(.001),s=real.Duration(1),valve=real.Valve('synthetic'),sensor=real.Sensor(400,'psi'))
sim_env={name:getattr(sim,name) for name in ['wait_for','wait_until','interval','Pressure','Valve','ValveState','psi','ms','s']}
sim_env.update(valve=sim.Valve('valve'),sensor=sim.Sensor('FTPT'))
cases=['wait_for(500*ms)','wait_for(500)','wait_for()', 'wait_until(lambda: sensor.read() > 300*psi, 5*s)', 'wait_until(lambda: True)', 'valve.open()', 'valve.open(True)', 'valve.actuate(True)', 'valve.actuate("OPEN")', 'valve.actuate(open=True)', 'sensor.read()', 'sensor.read(1)', 'sensor.open()', 'getattr(valve,"open")()', 'getattr(valve,"open")(True)', 'wait_for(*(1*ms,))', 'wait_for(**{"duration":1*ms})', 'Pressure(raw=True)', 'Pressure("3")', 'Pressure(1)/0','Pressure(-0.0)<Pressure(0.0)', 'Valve("missing")', 'ValveState.Open==2', 'ValveState.Open=="OPEN"', 'ValveState(2)', 'hash(ValveState.Open)', 'list(interval(True, 1*ms))','valve==Valve("synthetic")']
def outcome(expr,env):
 try:
  value=eval(expr,env)
  if value is None or isinstance(value,(bool,int,float,str,list)):return value
  return {'type':type(value).__name__}
 except BaseException as error:return {'exception':type(error).__name__}
print(json.dumps([{'expression':expr,'luna_extracted':outcome(expr,real_env),'tester':outcome(expr,sim_env)} for expr in cases],indent=2))
