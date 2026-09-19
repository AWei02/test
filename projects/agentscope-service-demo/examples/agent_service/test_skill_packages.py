"""ZIP checks and actual Docker execution; no LLM calls or real user records."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import subprocess

import skill_packages as packages
from agentscope.message import ToolResultState


def archive(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buffer.getvalue()


class ZipTests(unittest.TestCase):
    def test_traversal_and_missing_skill(self):
        for files in ({'../escape.py': 'x'}, {'/escape.py': 'x'}, {'folder/test.py': 'x'}):
            with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
                packages.extract_package(archive(files), Path(temp))

    def test_complete_package(self):
        with tempfile.TemporaryDirectory() as temp:
            root, meta, _ = packages.extract_package(archive({
                'demo/SKILL.md': '---\nname: demo\ndescription: test\n---\nRead scripts/demo.py',
                'demo/scripts/demo.py': 'print(42)', 'demo/assets/template.txt': 'template',
            }), Path(temp))
            self.assertEqual(meta['name'], 'demo')
            self.assertTrue((root / 'scripts/demo.py').exists())
            self.assertTrue((root / 'assets/template.txt').exists())


class DockerTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_runtime_and_revoke(self):
        import uuid
        tag = 'portal-skill-test:' + uuid.uuid4().hex
        try:
            with tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                root = directory / 'packages' / 's1' / 'content'
                root.mkdir(parents=True)
                (root / 'SKILL.md').write_text('---\nname: demo\ndescription: test\n---\nRun demo.py')
                (root / 'requirements.txt').write_text('colorama==0.4.6\n')
                (root / 'demo.py').write_text('import colorama, os, pathlib, socket\n'
                    'assert os.getuid() != 0\nassert not pathlib.Path("/workspace/projects").exists()\n'
                    'assert not pathlib.Path("/var/run/docker.sock").exists()\n'
                    'assert "OPENAI_API_KEY" not in os.environ\n'
                    'try:\n socket.create_connection(("1.1.1.1", 443), timeout=1)\n raise AssertionError("network available")\n'
                    'except OSError: pass\n'
                    'pathlib.Path("result.txt").write_text("RESULT_OK")\nprint("PYTHON_OK", colorama.__version__)\n')
                (root / 'demo.sh').write_text('cat /work/result.txt; echo SHELL_OK\n')
                packages.build_image(root, tag)
                (root.parent / 'manifest.json').write_text(json.dumps({'image': tag}))
                record = SimpleNamespace(id='s1', name='demo', description='test', markdown='test', enabled=True)
                selected = {'s1'}
                workspace = SimpleNamespace(username='test-user', agent='a', session='s',
                    selected=lambda field: selected,
                    storage=SimpleNamespace(get_skill=AsyncMock(return_value=record)))
                with patch.object(packages, 'ROOT', directory / 'packages'), patch.object(packages, 'WORK', directory / 'work'):
                    tool = packages.RunSkill(workspace)
                    result = await tool.call('s1', 'demo.py', 'run')
                    self.assertEqual(result.state, ToolResultState.SUCCESS)
                    self.assertIn('PYTHON_OK 0.4.6', result.content[0].text)
                    result = await tool.call('s1', 'demo.sh', 'run')
                    self.assertIn('RESULT_OK', result.content[0].text)
                    self.assertIn('SHELL_OK', result.content[0].text)
                    other = packages.workdir('other-user', 'a', 's')
                    self.assertFalse((other / 'result.txt').exists())
                    denied = await tool.call('s1', '../demo.py', 'run')
                    self.assertEqual(denied.state, ToolResultState.ERROR)
                    selected.clear()
                    denied = await tool.call('s1', 'demo.py', 'run')
                    self.assertEqual(denied.state, ToolResultState.ERROR)
        finally:
            subprocess.run(['docker', 'image', 'rm', tag], capture_output=True)


if __name__ == '__main__':
    unittest.main()
