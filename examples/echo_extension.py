"""Explicit opt-in plugin; Python plugins have the host user's permissions."""
from kotto import Tool


async def echo(args):return {'echo':args['text']}


def activate(host):
    host.register_tool(Tool('echo','Echo text for an integration check',{'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False},echo))
    host.register_command('hello',lambda text:'Hello '+text)
