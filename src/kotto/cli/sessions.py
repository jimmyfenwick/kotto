"""Explicit local session inspection; never contacts a model."""
import json
import re
from pathlib import Path
from kotto.session.store import Journal, SessionError

DEFAULT_ROOT = str(Path.home() / ".local/state/kotto/sessions")


def sessions(args):
    root = Path(args.session_root)
    if args.action == "list":
        print(json.dumps(sorted(p.name for p in root.iterdir() if p.is_dir() and re.fullmatch(r"[a-f0-9]{32}", p.name)) if root.exists() else []))
        return 0
    if not args.session_id: raise SessionError("A session ID is required.")
    with Journal(root, args.session_id) as store:
        if args.action == "show":
            print(json.dumps({"session_id": store.session_id, "messages": store.messages(), "uncertain": store.uncertain()}, ensure_ascii=False))
        else:
            if not args.artifact_id: raise SessionError("An artifact ID is required.")
            print(store.read_artifact(args.artifact_id))
    return 0
