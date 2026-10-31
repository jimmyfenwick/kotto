"""Application authorization; this is not an operating-system sandbox."""


class Policy:
    def __init__(self, *, allow_write=False, allow_shell=False, approve=None):
        self.allow_write, self.allow_shell, self.approve = allow_write, allow_shell, approve

    async def authorize(self, tool, args):
        if tool.effect == "read":
            return True
        if tool.effect not in {"write", "shell"}:
            return False
        if tool.effect == "write" and self.allow_write:
            return True
        if tool.effect == "shell" and self.allow_shell:
            return True
        return bool(await self.approve(tool, args)) if self.approve else False
