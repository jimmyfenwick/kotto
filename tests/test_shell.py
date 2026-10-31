import asyncio
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from kotto.tools.executor import ToolExecutor
from kotto.tools.policy import Policy


def command(code): return shlex.join([sys.executable, '-c', code])


class ShellTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_then_real_unittest_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'app.py').write_text('def add(a,b):\n    return a-b\n')
            Path(directory,'test_app.py').write_text('import unittest\nfrom app import add\nclass TestAdd(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(1,1),2)\n')
            tools = ToolExecutor(Path(directory), policy=Policy(allow_write=True,allow_shell=True))
            test_command = shlex.join([sys.executable,'-B','-m','unittest'])
            before = await tools.execute('1','shell',{'command':test_command})
            self.assertNotEqual(before.content['returncode'],0)
            read = await tools.execute('2','read',{'path':'app.py'})
            edit = await tools.execute('3','patch',{'path':'app.py','old_text':'a-b','new_text':'a+b','expected_sha256':read.content['sha256']})
            self.assertEqual(edit.status,'ok')
            after = await tools.execute('4','shell',{'command':test_command})
            self.assertEqual(after.content['returncode'],0)
    async def test_authorization_exit_and_bounded_output(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = ToolExecutor(Path(directory))
            args = {"command": command("print('hello'); raise SystemExit(7)")}
            self.assertEqual((await tools.execute("1", "shell", args)).status, "error")
            tools.policy = Policy(allow_shell=True)
            result = await tools.execute("2", "shell", args)
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.content["returncode"], 7)
            self.assertIn('hello', result.content['stdout'])
            result = await tools.execute("3", "shell", {"command": command("import sys; sys.stdout.write('x'*2000000)")})
            self.assertTrue(result.content['truncated'])
            self.assertLess(len(str(result.content)), 17000)

    async def test_timeout_and_cancellation_stop_descendants(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = ToolExecutor(Path(directory), policy=Policy(allow_shell=True))
            code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)']); open('pid','w').write(str(p.pid)); time.sleep(60)"
            result = await tools.execute('1','shell',{'command':command(code),'timeout':1})
            self.assertTrue(result.content['timed_out'])
            pid = Path(directory,'pid').read_text()
            process = await asyncio.create_subprocess_exec('ps','-o','stat=','-p',pid,stdout=asyncio.subprocess.PIPE)
            state = (await process.communicate())[0].decode().strip()
            self.assertTrue(not state or state.startswith('Z'),state)
            Path(directory,'pid').unlink()
            task = asyncio.create_task(tools.execute('2','shell',{'command':command(code)}))
            for _ in range(100):
                if Path(directory,'pid').exists(): break
                await asyncio.sleep(.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            pid = Path(directory,'pid').read_text()
            process = await asyncio.create_subprocess_exec('ps','-o','stat=','-p',pid,stdout=asyncio.subprocess.PIPE)
            state = (await process.communicate())[0].decode().strip()
            self.assertTrue(not state or state.startswith('Z'),state)
