<p align="center"><img src="docs/assets/kotto-avatar.png" width="240" alt="KOTTO mascot"></p>

# KOTTO

**A lightweight, extensible Python Agent Harness for reading, editing, and verifying local code.**

KOTTO connects models, context, tools, and sessions so an agent can search a repository, edit files, and run tests. It provides both a CLI and a Python embedding interface. The default provider is DeepSeek, using the configurable `deepseek-flash` model alias. DeepSeek currently maps this alias to Flash 4.1; provider aliases may change over time.

Version: **0.1.0**. Implementation and acceptance evidence are organized into [ten feature specifications](specs/README.md), with progress recorded in [status.json](specs/status.json). KOTTO is an independent Python implementation, not a compatibility port of Pi. Code is MIT-licensed; brand assets have separate terms.

## Installation

Requires Python 3.11+. Supported target platforms are macOS and Linux. Windows is not supported or verified: the current implementation relies on POSIX file locks and process groups.

```bash
git clone https://github.com/jimmyfenwick/kotto.git
cd kotto
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
kotto --version
```

`kotto` and `python -m kotto` use the same entry point. KOTTO has not been published to PyPI; install from source or a locally built wheel.

## Credentials outside the workspace

Keep credentials outside your repository. The recommended location is `~/.config/kotto/credentials.json`, with permissions set to `600`:

```json
{"DEEPSEEK_API_KEY": "your-api-key"}
```

The file must be outside the configured workspace and accessible only to its owner. Select it explicitly with the global `--credentials-file` option. KOTTO does not search for credential files or automatically load `.env` files.

```bash
kotto --credentials-file ~/.config/kotto/credentials.json doctor --json
kotto --credentials-file ~/.config/kotto/credentials.json chat 'Hello'
kotto --credentials-file ~/.config/kotto/credentials.json run 'Find and explain the entry point of this repository'
```

`doctor` checks local configuration only. A complete configuration does not prove that remote authentication works. `chat` and `run` make actual model requests. Credential files are read into memory; their contents are not copied into the project or written to session history.

Environment variables are also supported. An environment variable overrides the file value with the same name:

| Setting | Default or behavior |
|---|---|
| `KOTTO_API_KEY` | Takes precedence over `DEEPSEEK_API_KEY`; an explicitly empty value does not fall back |
| `DEEPSEEK_API_KEY` | Used when `KOTTO_API_KEY` is not defined |
| `KOTTO_BASE_URL` | `https://api.deepseek.com` |
| `KOTTO_MODEL` | `deepseek-flash`, currently mapped to Flash 4.1 |
| `KOTTO_WORKSPACE` | Current directory; must exist |

The initial provider uses Chat Completions with SSE streaming and disables thinking mode by default. Reasoning content and tool calls returned by the provider are preserved; plain terminal output displays the answer. Requests are not retried automatically, redirects are not followed, and the HTTP client connects directly without reading proxy environment variables. DeepSeek has been verified; compatibility with every OpenAI-compatible service is not claimed.

## File and command authorization

Runs are read-only by default. Write and shell tools are defined, but the executor rejects unauthorized operations. The model cannot grant itself permissions.

```bash
kotto --credentials-file ~/.config/kotto/credentials.json run 'Fix this bug and run the existing tests' --allow-write --allow-shell
```

- `--allow-write` authorizes file creation and exact replacement. Read the file first and supply its SHA256 hash. Changes to the file or ambiguous replacements cause a conflict. Creating a file never overwrites an existing file.
- `--allow-shell` explicitly authorizes commands on the **local host**, with the current user's process permissions. **This is not a sandbox.** Working directories are checked, but commands can still access host files and the network. Run the entire process in a container or virtual machine you manage if you need stronger isolation.
- `--ask` requests approval for each non-read operation. It requires an interactive terminal and rejects JSON or non-terminal use. It cannot be combined with interactive steering.

File tools reject paths outside the workspace and symlink escapes. They hide `.git`, `.venv`, `.kotto`, `node_modules`, environment files, and `credentials.json`. Source files are limited to 1 MiB, with at most 200 lines displayed per read. Search scans at most 1,000 candidate files and returns at most 100 matches, marking truncation when a limit is reached.

Tool results include actual exit codes, timeout information, and truncation indicators. Each command output stream displays at most 6,000 bytes; session artifacts retain the first 512 KiB per stream and explicitly flag further truncation. Capture is bounded in memory and on disk. Timeout and cancellation clean up the process group, including descendants that ignore SIGTERM.

## Sessions and recovery

Each `run` prints a session ID. Sessions are stored in `~/.local/state/kotto/sessions` by default; override this with `--session-root`. Logs may contain user input and source code. They stay on the local machine and can be removed according to your retention needs.

```bash
kotto sessions list
kotto sessions show SESSION_ID
kotto --credentials-file ~/.config/kotto/credentials.json run 'Continue the unfinished task' --session SESSION_ID
```

A resumed session must use the same workspace and cannot expand its original permissions. Pass the relevant flags again when resuming a session that previously allowed writes. Sessions use a single-writer lock, a versioned append-only journal, and durable intent records before tool execution. After a crash, calls without confirmed results remain uncertain and **are not replayed automatically**.

After inspecting the actual files or process state, use `--acknowledge-unknown` to acknowledge uncertainty and resume. This records an unknown result rather than inventing success. Inspect partial side effects after cancellation as well. Exactly-once execution cannot be guaranteed for arbitrary external operations.

Use `kotto sessions artifact SESSION_ID ARTIFACT_ID` to inspect large results. Agents can read bounded slices of current-session artifacts through `artifact_read`.

## Run control and context

```bash
kotto --credentials-file ~/.config/kotto/credentials.json run 'Analyze this project' --max-rounds 12 --max-tool-calls 64 --timeout 300
kotto --credentials-file ~/.config/kotto/credentials.json run 'Work through this task' --interactive
```

Interactive mode accepts `/steer additional instructions` and `/cancel`. Steering messages are applied in order before the next model round, without replaying completed tools. Ctrl-C cancels the operation and triggers cleanup.

`--max-total-tokens` stops further work after cumulative provider-reported usage reaches its limit. The current request may exceed that threshold; this is not a hard billing cap. Costs are not estimated when pricing is unknown. `--max-rounds` limits the main Agent loop; history summarization can make additional model requests, which count toward total time and reported token usage.

A workspace-root `AGENTS.md` applies throughout the workspace. Nested instructions apply only to relevant paths. New or changed rules must enter the context before editing. Project rules do not override explicit user instructions, and files or tool outputs do not gain higher instruction priority.

`--context-window` defaults to 64000 and `--context-reserve` to 4096. These use a conservative UTF-8 byte-based estimate, **not an exact tokenizer**. Long histories are summarized in bounded chunks while retaining all user requests verbatim, recent complete tool exchanges, and the original journal. Required content that still exceeds the budget, or a failed summary, produces an explicit error instead of silently dropping constraints. Summaries can omit facts; original records remain available, and restored tasks should verify the current file state.

## Extensions and Skills

```bash
kotto --credentials-file ~/.config/kotto/credentials.json run 'Call the echo tool' --extension examples/echo_extension.py
kotto command hello world --extension examples/echo_extension.py
kotto --credentials-file ~/.config/kotto/credentials.json run 'Review this project using the guide' --skill /external/path/SKILL.md
```

Python extensions are **trusted host code**. Explicitly enabling one allows it to run inside the current process. KOTTO does not automatically discover, download, or execute repository plugins, and does not provide a plugin sandbox. Registered tools use the shared validation, authorization, and journaling path, but plugin code itself can execute arbitrary Python. Tool policy cannot isolate a malicious plugin.

`activate(host)` can register a `Tool`, commands, and event subscribers, and return an optional synchronous cleanup function. A Skill is a text guide that applies when explicitly enabled for a run and counts toward its context budget. Each guide is limited to 64 KiB.

Embed KOTTO in Python:

```python
import asyncio
import os
from contextlib import aclosing
from kotto import Settings, create_agent

async def main():
    settings = Settings.from_env(os.environ)
    async with create_agent(settings) as agent:
        async with aclosing(agent.run('Find the repository entry point')) as events:
            async for event in events:
                print(event.kind, event.data)

asyncio.run(main())
```

Use `aclosing` or explicitly call `await stream.aclose()` when stopping consumption early so the run can clean up immediately. Simply stopping reads without closing the stream cannot be detected immediately; the total timeout still applies. See [examples](examples/README.md) and the [architecture guide](docs/architecture.md) for more detail.

## Project structure

```text
src/kotto/
  contracts/    # Model/Agent events and correlated tool results
  model/        # DeepSeek streaming adapter and public Protocol
  runtime/      # Agent loop, cancellation, queues, and budgets
  tools/        # Validation, policy, reads, atomic edits, and host commands
  context/      # Scoped rules, budgets, and non-destructive compaction
  session/      # Single-writer journal, recovery, and artifacts
  extensions/   # Explicit trusted plugins and text guides
  cli/          # Terminal input, JSON events, and run controls
  config.py     # External configuration and credential redaction
  bootstrap.py  # Dependency assembly and create_agent
specs/          # Ten feature specifications, status, and evidence
```

## Tests and acceptance

```bash
python -m pip install '.[dev]'
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
```

Default tests run offline and cover local HTTP streaming, permissions, conflicts, process cleanup, recovery, compaction, and extensions. They do not require an API key. CI covers macOS/Linux and Python 3.11/3.12. Live model acceptance is explicitly enabled through [evals/run_live.py](evals/run_live.py). It incurs model usage, runs independent checks in a synthetic temporary repository, and does not modify user projects.

JSON output is a stream of line-delimited events that distinguishes text deltas, complete model messages, tool results, and run termination. `run_end.reason` describes execution state; **a completed model answer does not prove that the user's task passed acceptance**. Check actual test exit codes and file changes.

Exit codes: 0 for success; 1 for model, runtime, or budget errors; 2 for configuration errors or a not-ready `doctor` result; 130 for user cancellation.

The initial release does not include a web UI, multi-agent orchestration, long-term memory, a plugin marketplace, Windows support, or production deployment. It has not been published to PyPI. Code and technical documentation use the [MIT License](LICENSE); visual brand assets follow [BRAND.md](BRAND.md).
