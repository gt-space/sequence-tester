"""Mutate only disposable source copies to verify contract failure behavior."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
source=Path(sys.argv[1])
cases=[
 ('removed export','common/src/sequence/mod.rs','module.add_function(wrap_pyfunction!(wait_for, module)?)?;',''),
 ('added export','common/src/sequence/mod.rs','module.add_class::<Sensor>()?;','module.add_class::<Sensor>()?;\nmodule.add("new_export", 1)?;'),
 ('renamed parameter','common/src/sequence/func.rs','pub fn wait_for(duration: Duration)','pub fn wait_for(delay: Duration)'),
 ('changed signature','common/src/sequence/device.rs','pub fn open(&self)','pub fn open(&self, flag: bool)'),
 ('changed optional','common/src/sequence/func.rs','timeout: Option<Duration>','timeout: Duration'),
 ('binding attributes','common/src/sequence/func.rs','#[pyfunction]\npub fn wait_for','#[pyo3(signature = (duration, /))]\n#[pyfunction]\npub fn wait_for'),
 ('unit behavior','common/src/sequence/unit.rs','raw: self.raw + other.raw','raw: self.raw - other.raw'),
 ('measurement conversion','common/src/sequence/unit.rs','Unit::Psi => Pressure::new(self.value)','Unit::Psi => Pressure::new(self.value * 2.0)'),
 ('enum state','common/src/comm/gui.rs','    Undetermined,','    NewState,\n    Undetermined,'),
 ('prelude','flight2/src/sequence.rs','OPEN = ValveState.Open;','OPEN = ValveState.Closed;'),
 ('sensor ordering','common/src/sequence/device.rs','other.rich_compare(self.read()?, op)?','self.read()?.rich_compare(other, op)?'),
]
rows=[]
with tempfile.TemporaryDirectory(prefix='luna-drift-audit-') as tmp:
 copy=Path(tmp)
 for path in ['common/src/sequence/mod.rs','common/src/sequence/func.rs','common/src/sequence/device.rs','common/src/sequence/unit.rs','common/src/comm/gui.rs','flight2/src/sequence.rs','Cargo.lock','common/Cargo.toml','common/src/comm/flight.rs','common/src/comm/sam.rs','gui/src/system/SystemPages.tsx','gui/src/comm.tsx','servo/src/server/routes/sequence.rs']:
  if not (source/path).is_file():continue
  p=copy/path;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/path,p)
 for name,path,old,new in cases:
  p=copy/path;original=p.read_text()
  if old not in original:raise RuntimeError(f'Mutation did not apply: {name}')
  p.write_text(original.replace(old,new,1))
  row={'mutation':name}
  for script in ['check_luna_contract.py','generate_luna_contract.py']:
   run=subprocess.run([sys.executable,str(root/'scripts'/script),str(copy)],capture_output=True,text=True)
   row[script]=run.returncode
   if run.returncode==0:raise AssertionError(f'False green: {name}: {script}')
  rows.append(row);p.write_text(original)
print(json.dumps(rows,indent=2))
