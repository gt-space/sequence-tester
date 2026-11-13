"""Compatibility metadata and Rust-surface extractor regression coverage."""
import ast
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_luna_contract import comparison_order, extract, render
from write_luna_status import build_status


class CompatibilityTests(unittest.TestCase):
    def test_sensor_comparison_order_detects_upstream_change(self):
        reverse = """#[pymethods]
impl Sensor {
    fn __richcmp__(&self, other: &PyAny, op: CompareOp) -> PyResult<bool> {
        other.rich_compare(self.read()?, op)?.is_truthy()
    }
}"""
        normal = reverse.replace("other.rich_compare(self.read()?, op)?",
                                 "self.read()?.rich_compare(other, op)?")
        self.assertEqual(comparison_order(reverse), "reversed")
        self.assertEqual(comparison_order(normal), "normal")
        with self.assertRaises(ValueError):
            comparison_order(reverse.replace("other.rich_compare(self.read()?, op)?", "unknown()"))

    def test_extracts_public_bindings_into_executable_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            seq = root / "common" / "src" / "sequence"
            seq.mkdir(parents=True)
            (seq / "mod.rs").write_text("""
module.add_class::<Sensor>()?;
module.add_class::<Valve>()?;
module.add_class::<Duration>()?;
module.add_class::<ValveState>()?;
module.add("ms", Py::new(py, Duration::new(0.001))?)?;
module.add("__layout_fingerprint__", 1)?;
module.add_function(wrap_pyfunction!(wait_for, module)?)?;
""")
            (seq / "func.rs").write_text("#[pyfunction]\npub fn wait_for(duration: Duration) {}\n")
            (seq / "unit.rs").write_text("""
pub fn new(raw: f64) -> Self { Self { raw } }
create_unit!(Duration, "s");
""")
            (seq / "device.rs").write_text("""
#[pymethods]
impl Sensor {
    #[new]
    pub fn new(name: String) -> Self { todo!() }
    pub fn read(&self) -> PyResult<PyObject> { todo!() }
    fn __richcmp__(&self, other: &PyAny, op: CompareOp) -> PyResult<bool> {
        other.rich_compare(self.read()?, op)?.is_truthy()
    }
}
#[pymethods]
impl Valve {
    #[new]
    pub fn new(name: String) -> Self { todo!() }
    pub fn open(&self) -> PyResult<()> { todo!() }
}
""")
            gui = root / "common" / "src" / "comm"
            gui.mkdir(parents=True)
            (gui / "gui.rs").write_text("""pub enum ValveState {
    Open,
    Closed,
}""")
            flight = root / "flight2" / "src"
            flight.mkdir(parents=True)
            (flight / "sequence.rs").write_text(
                'let x = "OPEN = ValveState.Open;CLOSED = ValveState.Closed;";'
            )
            contract = extract(root)
            self.assertEqual(contract["FUNCTIONS"]["wait_for"], (("duration", "Duration"),))
            self.assertEqual(contract["METHODS"]["Valve"]["open"], ())
            self.assertEqual(contract["UNIT_CONSTANTS"]["ms"], "s")
            self.assertEqual(contract["SENSOR_COMPARISON_ORDER"], "reversed")
            ast.parse(render(contract))

    def test_versioned_status_cannot_claim_compatibility_without_revision(self):
        sha = "a" * 40
        result = build_status("live", sha, "b" * 40, False, "changed")
        self.assertFalse(result["compatible"])
        self.assertEqual(result["luna_sha"], sha)
        self.assertIn("changed", result["error"])
        with self.assertRaises(ValueError):
            build_status("build", "unknown", "b" * 40)


if __name__ == "__main__":
    unittest.main()
