import sys,json,operator
from pathlib import Path
sys.path[:0]=[sys.argv[1],str(Path(__file__).resolve().parents[1]/'src')]
import luna_probe as real
from engine import Simulator
ops={'<':operator.lt,'<=':operator.le,'==':operator.eq,'!=':operator.ne,'>':operator.gt,'>=':operator.ge}
def outcome(f):
 try:return f()
 except BaseException as e:return type(e).__name__
rows=[]
for unit in ['psi','unknown','V','missing']:
 for value in [0,299,300,301,400]:
  sim=Simulator({}, {'FTPT':{'unit':unit if unit!='missing' else 'psi','samples':[{'at':0,'value':value}],'interpolation':'step'}})
  m=sim.make_module(); a=real.Sensor(value,unit);b=m.Sensor('FTPT')
  for symbol,op in ops.items():
   for expression in ['sensor OP threshold','threshold OP sensor','sensor.read() OP threshold','threshold OP sensor.read()']:
    expr=expression.replace('OP',symbol)
    r=outcome(lambda:eval(expr,{'sensor':a,'threshold':real.Pressure(300)}))
    s=outcome(lambda:eval(expr,{'sensor':b,'threshold':300*m.psi}))
    rows.append(dict(unit=unit,value=value,expression=expr,luna=r,tester=s,equal=r==s))
print(json.dumps(rows,indent=2))
