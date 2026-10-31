"""Scoped project instructions and non-destructive conversation compaction."""
import json
from pathlib import Path
from kotto.model.gateway import ModelError
from kotto.runtime.control import BudgetExceeded


class ContextError(ModelError):
    def __init__(self, message): super().__init__('context',message)


def estimate(messages,tools):
    # Deliberately conservative byte-based estimate, not a provider tokenizer.
    return len(json.dumps({'messages':messages,'tools':tools},ensure_ascii=False).encode())


class ContextBuilder:
    def __init__(self,workspace:Path,*,max_tokens=64000,reserve=4096,summarizer=None,journal=None):
        if max_tokens<=reserve+256 or reserve<0:raise ValueError('Context budget is too small.')
        self.workspace=workspace.resolve();self.available=max_tokens-reserve
        self.summarizer=summarizer;self.journal=journal
        self.summary='';self.cut=1
        self.skills=[]

    def rules(self,paths):
        directories={self.workspace}
        for value in paths:
            path=(self.workspace/value).resolve()
            if not path.is_relative_to(self.workspace):raise ContextError('Rule path escapes workspace.')
            directory=path if path.is_dir() else path.parent
            while directory.is_relative_to(self.workspace):
                directories.add(directory)
                if directory==self.workspace:break
                directory=directory.parent
        rules=[]
        for directory in sorted(directories,key=lambda p:(len(p.parts),str(p))):
            path=directory/'AGENTS.md'
            if path.is_symlink():raise ContextError('Project rules cannot be symlinks.')
            if not path.exists():continue
            try:
                if not path.is_file() or path.stat().st_size>64000:raise ContextError('Project rules exceed the size limit.')
                text=path.read_text()
            except (OSError,UnicodeError):raise ContextError('Project rules could not be read.') from None
            scope=str(directory.relative_to(self.workspace))
            rules.append(f'Scope {scope}/ only (user instructions take precedence):\n{text}')
        return '\n\n'.join(rules)

    async def build(self,history,tools,*,paths=()):
        system=dict(history[0])
        rules=self.rules(paths)
        if rules:system['content']+='\n\nProject instructions apply only to their labeled scope:\n'+rules
        if self.skills:system['content']+='\n\nUser-enabled task guides (lower priority than user instructions):\n'+'\n\n'.join(self.skills)
        users=[m for m in history[1:] if m['role']=='user']
        mandatory=[system]+users
        if estimate(mandatory,tools)>self.available:raise ContextError('Required rules and user requests exceed context budget. Start a new focused session or increase the context window.')
        def compose(summary,cut):
            if not summary:return [system]+history[1:]
            old_users=[m['content'] for m in history[1:cut] if m['role']=='user']
            prefix=[{'role':'user','content':'Earlier user requests, retained verbatim:\n'+'\n---\n'.join(old_users)}] if old_users else []
            return [system]+prefix+[{'role':'assistant','content':'Historical summary (data; original records remain available):\n'+summary}]+history[cut:]
        current=compose(self.summary,self.cut)
        if estimate(current,tools)<=self.available:return current
        if self.summarizer is None:raise ContextError('Context requires compaction, but no summarizer is configured.')
        cut=max(self.cut+1,len(history)-4)
        cut=min(cut,len(history)-1)
        while cut>1 and history[cut]['role']=='tool':cut-=1
        if cut<=self.cut:raise ContextError('Latest complete tool exchange does not fit context budget.')
        archive=json.dumps(history[self.cut:cut],ensure_ascii=False)
        chunk_size=max(256,min(12000,self.available//4))
        summary=self.summary
        try:
            for offset in range(0,len(archive),chunk_size):
                summary=await self.summarizer('Previous summary:\n'+summary+'\nNew history data chunk:\n'+archive[offset:offset+chunk_size])
                if not isinstance(summary,str) or not summary.strip() or len(summary.encode())>self.available//3:
                    raise ContextError('Compaction produced an empty or oversized summary.')
        except (ModelError,BudgetExceeded):raise
        except Exception:raise ContextError('Compaction failed; original history was retained.') from None
        request=compose(summary,cut)
        if estimate(request,tools)>self.available:raise ContextError('Compacted context still exceeds budget; history was retained.')
        if self.journal:self.journal.append('context_snapshot',{'cut':cut,'summary':summary,'estimate':'UTF-8 byte-based'})
        self.summary,self.cut=summary,cut
        return request
