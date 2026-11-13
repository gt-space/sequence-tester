"""Build-source generator for an isolated compiled-binding audit (NO FC IPC).

Usage: python3 scripts/build_luna_audit_harness.py UPSTREAM_ARCHIVE OUTPUT_DIRECTORY
Then cargo build --manifest-path OUTPUT_DIRECTORY/Cargo.toml.
Copies unit.rs, Measurement conversion, Sensor.__richcmp__, wait_for/wait_until
and interval unchanged. Measurement container and Sensor.read are synthetic.
This is extracted binding evidence, NOT the complete common production module.
"""
import argparse
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("upstream",type=Path)
parser.add_argument("output",type=Path)
args=parser.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
(args.output/"src").mkdir(exist_ok=True)
(args.output/"Cargo.toml").write_text('''[package]
name = "luna-binding-audit"
version = "0.1.0"
edition = "2021"
[lib]
name = "luna_probe"
crate-type = ["cdylib"]
[dependencies]
pyo3 = { version = "=0.21.2", features = ["abi3-py38", "extension-module", "gil-refs"] }
''')
root=args.upstream/'common/src/sequence' 
unit=(root/'unit.rs').read_text()
device=(root/'device.rs').read_text()
rich=device[device.index('    fn __richcmp__'):device.index('\n}\n', device.index('    fn __richcmp__'))]
# Exact upstream unit module and Measurement conversion, controlled synthetic read
prefix='''use pyo3::prelude::*;
mod comm {
    pub mod sam { pub enum Unit { Unknown, Amps, Kelvin, Pounds, Psi, Volts } }
    pub struct Measurement { pub value: f64, pub unit: sam::Unit }
}
mod unit {
'''
suffix='''
}
use pyo3::pyclass::CompareOp;
#[pyclass]
struct Sensor { value: f64, kind: String }
#[pymethods]
impl Sensor {
    #[new]
    fn new(value: f64, kind: String) -> Self { Self { value, kind } }
    fn read(&self) -> PyResult<PyObject> {
        let unit = match self.kind.as_str() {
            "psi" => comm::sam::Unit::Psi, "V" => comm::sam::Unit::Volts,
            "A" => comm::sam::Unit::Amps, "K" => comm::sam::Unit::Kelvin,
            "lbf" => comm::sam::Unit::Pounds, "unknown" => comm::sam::Unit::Unknown,
            _ => return Err(pyo3::exceptions::PyKeyError::new_err("synthetic missing sensor")),
        };
        Ok(Python::with_gil(|py| comm::Measurement { value: self.value, unit }.into_py(py)))
    }
'''+rich+'''
}
#[pymodule]
fn luna_probe(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<Sensor>()?;
'''+''.join(f'    m.add_class::<unit::{name}>()?;\n' for name in ['Current','Duration','ElectricPotential','Force','Pressure','Temperature'])+'''    Ok(())
}
'''
(args.output/'src/lib.rs').write_text(prefix+unit+suffix)
import re
p=(args.output/'src/lib.rs'); text=p.read_text()
func=(root/'func.rs').read_text()
# Actual non-IPC timing functions and iterator copied unchanged.
start=func.index('/// A Python-exposed function which waits the thread')
end=func.index('/// Python exposed function that lets operators')
timing=func[start:end]
iterator=func[func.index('/// Iterator which only yields'):]
text=text.replace('use pyo3::pyclass::CompareOp;', 'use pyo3::{pyclass::CompareOp, PyRef, PyRefMut, pyfunction};\nuse std::{thread,time::Instant};\nuse unit::Duration;\n'+timing+'\n'+iterator)
text=text[:text.rfind('    Ok(())\n}')] + '    m.add_function(wrap_pyfunction!(wait_for,m)?)?;\n    m.add_function(wrap_pyfunction!(wait_until,m)?)?;\n    m.add_function(wrap_pyfunction!(interval,m)?)?;\n    Ok(())\n}'
p.write_text(text)

# Retain Valve's actual declaration/constructors/method signatures, but replace
# its state read and actuation bodies so there is no path to a socket or mmap.
def replace_body(source, marker, replacement):
    start = source.index('{', source.index(marker))
    depth = 1
    end = start + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[:start] + '{' + replacement + '}' + source[end:]

valve = device[device.index('/// A Python-exposed class that allows for interacting with a valve.'):]
valve = replace_body(valve, 'fn is_state(', ' Ok(false) ')
valve = replace_body(valve, 'pub fn actuate(', ' Ok(()) ')
gui = (args.upstream/'common/src/comm/gui.rs').read_text()
enum = gui[gui.index('pub enum ValveState'):]
enum = enum[:enum.index('\n}') + 2]
extra = '#[pyclass]\n#[derive(Clone,Copy)]\n' + enum + '\n' + valve
text = p.read_text().replace('#[pymodule]', extra + '\n#[pymodule]')
text = text.replace('    m.add_class::<Sensor>()?;', '    m.add_class::<Valve>()?;\n    m.add_class::<ValveState>()?;\n    m.add_class::<Sensor>()?;')
p.write_text(text)
