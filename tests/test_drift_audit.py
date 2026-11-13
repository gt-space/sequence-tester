"""Independent source-copy mutations must invalidate a checked contract."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from generate_luna_contract import extract

class DriftAudit(unittest.TestCase):
    def test_behavior_and_pyo3_attributes_are_part_of_contract(self):
        # Reuse a realistic fixture built by the extractor regression test.
        import test_luna_compatibility
        with tempfile.TemporaryDirectory() as tmp:
            # Populate using the existing fixture without touching Luna.
            original=tempfile.TemporaryDirectory
            class Keep:
                def __enter__(self): return tmp
                def __exit__(self,*args): pass
            tempfile.TemporaryDirectory=lambda: Keep()
            try: test_luna_compatibility.CompatibilityTests('test_extracts_public_bindings_into_executable_contract').test_extracts_public_bindings_into_executable_contract()
            finally: tempfile.TemporaryDirectory=original
            root=Path(tmp);before=extract(root)
            for path,old,new in [('common/src/sequence/func.rs','#[pyfunction]','#[pyo3(signature = (duration, /))]\n#[pyfunction]'),('common/src/sequence/unit.rs','Self { raw }','Self { raw: raw * 2.0 }')]:
                p=root/path;source=p.read_text();p.write_text(source.replace(old,new))
                self.assertNotEqual(before,extract(root),path)
                p.write_text(source)
