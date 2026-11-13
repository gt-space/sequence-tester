import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class IsolationRunner(unittest.TestCase):
    def test_bubblewrap_never_shares_the_host_network(self):
        spec=importlib.util.spec_from_file_location('runner',ROOT/'scripts/test_production_binding.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        prefix=module.namespace_prefix()
        self.assertEqual(prefix[0],'unshare')
        split=prefix.index('bwrap')
        self.assertIn('--net',prefix[:split])
        self.assertIn('--user',prefix[:split])
        self.assertIn('--unshare-all',prefix[split:])
        self.assertIn('--share-net',prefix[split:])
