import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from rasbot.agent_runtime import executable


@unittest.skipUnless(os.name == 'nt', 'Windows executable discovery')
class ExecutableDiscoveryTests(unittest.TestCase):
    def test_native_path_precedes_npm_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'opencode.exe'
            binary.touch()
            with patch.dict(os.environ, {'RASBOT_OPENCODE_BIN':''}), patch('rasbot.agent_runtime.shutil.which', return_value=str(binary)):
                self.assertEqual(executable('opencode'),[str(binary)])
