import tempfile
import unittest
from pathlib import Path
from kotto import Settings, create_agent
from kotto.extensions.host import ExtensionError
from kotto.contracts.event import ModelEvent


class FakeModel:
    async def stream(self,messages,**kwargs):
        if messages[-1]['role']=='user' and messages[-1]['content']=='use echo':
            yield ModelEvent('message',{'role':'assistant','content':None,'tool_calls':[{'id':'echo1','type':'function','function':{'name':'echo','arguments':'{"text":"from model"}'}}]})
        else:yield ModelEvent('message',{'role':'assistant','content':'done'})


class ExtensionTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_plugin_tool_command_and_sdk(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            plugin=root/'plugin.py'
            plugin.write_text("from kotto import Tool\nasync def echo(args): return {'text':args['text']}\ndef activate(host):\n    host.register_tool(Tool('echo','Echo input',{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False},echo))\n    host.register_command('hello',lambda text:'Hello '+text)\n")
            settings=Settings('https://example.invalid','fake',root,'')
            agent=create_agent(settings,model=FakeModel())
            self.assertNotIn('echo',agent.tools.tools)
            await agent.aclose()
            async with create_agent(settings,model=FakeModel(),extensions=[plugin]) as agent:
                result=await agent.tools.execute('c','echo',{'text':'hi'})
                self.assertEqual(result.content,{'text':'hi'})
                self.assertEqual(await agent.extensions.command('hello','world'),'Hello world')
                events=[e async for e in agent.run('use echo')]
                self.assertEqual(events[-1].data['reason'],'completed')
                self.assertTrue(any(e.kind=='tool_end' and e.data['name']=='echo' for e in events))

    async def test_duplicate_listener_failure_and_skill_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=Settings('https://example.invalid','fake',root,'')
            skill=root/'SKILL.md';skill.write_text('Follow the user-enabled guide.')
            async with create_agent(settings,model=FakeModel(),skills=[skill]) as agent:
                self.assertIn('user-enabled guide',str(await agent.context.build(agent.messages+[{'role':'user','content':'test'}],[])))
                with self.assertRaises(ValueError):agent.extensions.register_tool(agent.tools.tools['read'])
                def fail(event):raise RuntimeError('private diagnostic')
                agent.extensions.subscribe(fail)
                events=[e async for e in agent.run('test')]
                self.assertEqual(events[-1].data['reason'],'failed')
                self.assertNotIn('private diagnostic',str(events))
            with self.assertRaises(ExtensionError):create_agent(settings,skills=[root/'missing'])

    async def test_extension_write_policy_and_skill_overflow(self):
        from kotto import Tool
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);settings=Settings('https://example.invalid','fake',root,'')
            async with create_agent(settings,model=FakeModel()) as agent:
                calls=[]
                async def write(args):calls.append(args);return {'changed':True}
                agent.extensions.register_tool(Tool('extension_write','Write test',{'type':'object','properties':{},'additionalProperties':False},write,'write'))
                self.assertEqual((await agent.tools.execute('1','extension_write',{})).status,'error')
                self.assertEqual(calls,[])
            skill=root/'SKILL.md';skill.write_text('x'*10000)
            async with create_agent(settings,model=FakeModel(),skills=[skill],context_window=5000,context_reserve=200) as agent:
                events=[e async for e in agent.run('test')]
                self.assertEqual(events[-1].data['reason'],'failed')
