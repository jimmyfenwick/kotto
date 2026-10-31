<p align="center"><img src="docs/assets/kotto-avatar.png" width="240" alt="扣仔 KOTTO"></p>

# KOTTO · 扣仔

**轻量、可扩展的 Python Agent Harness，用于本地代码阅读、修改和验证。**

KOTTO 管理模型、上下文、工具和会话，让模型能够实际搜索仓库、编辑代码和运行测试。支持 CLI 与 Python 嵌入；默认接入 DeepSeek，模型标识为 `deepseek-flash`。官方文档当前将它映射到 Flash 4.1；服务别名可能变化，支持通过配置覆盖。

版本：**0.1.0**。实现与证据按 [十个功能规格](specs/README.md) 组织，当前状态见 [status.json](specs/status.json)。独立 Python 实现，不是 Pi 的兼容移植。代码使用 MIT，扣仔视觉素材单独约定。

## 安装

支持 Python 3.11+，目标平台为 macOS/Linux。Windows 未验证，当前依赖 POSIX 文件锁与进程组，不宣称支持。

```bash
git clone https://github.com/jimmyfenwick/kotto.git
cd kotto
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
kotto --version
```

`kotto` 与 `python -m kotto` 是相同入口。未发布 PyPI，请从源码或构建出的 wheel 安装。

## 项目外配置凭据

推荐在 `~/.config/kotto/credentials.json` 保存，权限设为 `600`，内容如下（自行填入真实 Key，不提交仓库）：

```json
{"DEEPSEEK_API_KEY": "你的 Key"}
```

文件必须在工作区外、仅当前用户可读写，并显式通过全局选项指定。程序不自动搜索凭据文件，也不自动加载 `.env`。

```bash
kotto --credentials-file ~/.config/kotto/credentials.json doctor --json
kotto --credentials-file ~/.config/kotto/credentials.json chat '你好'
kotto --credentials-file ~/.config/kotto/credentials.json run '搜索并解释这个仓库的入口文件'
```

`doctor` 只检查本地配置，配置齐全不代表远程认证已通过。真实请求由 `chat` 或 `run` 发起。凭据文件只在内存中读取，不复制到项目或写入会话。

也可使用环境变量；同名环境变量覆盖文件值：

| 配置 | 默认值 / 行为 |
|---|---|
| `KOTTO_API_KEY` | 优先于 `DEEPSEEK_API_KEY`；显式空值不会回退 |
| `DEEPSEEK_API_KEY` | 没有定义 `KOTTO_API_KEY` 时使用 |
| `KOTTO_BASE_URL` | `https://api.deepseek.com` |
| `KOTTO_MODEL` | `deepseek-flash`，当前对应 Flash 4.1 |
| `KOTTO_WORKSPACE` | 当前目录；必须存在 |

首版使用 Chat Completions SSE 协议，默认关闭思考模式。保留服务实际返回的思考内容与工具调用；普通终端只展示回答。没有自动重试，不跟随重定向，网络客户端直接连接，不读取代理环境变量。仅验证 DeepSeek，不承诺全部兼容服务。

## 读写与命令授权

默认只读。写入与 shell 都有工具定义，但未获授权时执行器会拒绝；模型无法自行打开权限。

```bash
kotto --credentials-file ~/.config/kotto/credentials.json run '修复这个 bug 并运行现有测试' --allow-write --allow-shell
```

- `--allow-write`：允许新建文件和精确替换。先读取 SHA256，再提供预期哈希；文件变化或替换不唯一时拒绝覆盖。新建不覆盖已有文件。
- `--allow-shell`：明确允许在**宿主系统**执行命令，具备当前用户的进程权限，**不是沙箱**。工作目录受检查，但命令本身仍能访问宿主文件与网络。需要强隔离时，请把整个进程放进自己管理的容器或虚拟机。
- `--ask`：逐次询问非只读操作；需要交互终端，JSON 模式及无终端时拒绝。它不能与交互式 steering 同时使用。

文件工具拒绝工作区外路径和符号链接逃逸；默认隐藏 `.git`、`.venv`、`.kotto`、`node_modules`、环境文件与 credentials.json。源文件最多读取 1 MiB，每次最多展示 200 行。搜索最多扫描 1000 个候选文件，最多返回 100 条命中，超限会标记。

工具结果包含真实退出码、超时和截断信息。命令 stdout/stderr 各展示最多 6000 字节；会话附件各保留前 512 KiB，超过仍标记截断。大输出不会无限占用内存或磁盘。超时和取消会清理整个进程组，包含忽略 SIGTERM 的后代。

## 会话与恢复

每次 `run` 输出一个 session ID。默认保存在 `~/.local/state/kotto/sessions`，可用 `--session-root` 修改；日志可能包含用户输入和代码，保留在本机，需自行按需求删除。

```bash
kotto sessions list
kotto sessions show SESSION_ID
kotto --credentials-file ~/.config/kotto/credentials.json run '继续未完成任务' --session SESSION_ID
```

恢复时须使用同一工作区，不能扩大原会话的权限；如原会话允许写入，需再次显式传递相应标志。会话采用单写入者锁、版本化追加日志和执行前意图记录。进程崩溃后，未得到结果的调用保持不确定，**不会自动重放**。

检查实际文件或进程状态后，可通过 `--acknowledge-unknown` 明确确认，再恢复。确认仅记录 unknown，不把未确认操作伪装为成功。取消后的部分副作用也需要检查。工具与外部系统之间无法保证任意操作恰好执行一次。

查看大结果可用 `kotto sessions artifact SESSION_ID ARTIFACT_ID`；Agent 可调用 `artifact_read` 分段读取当前会话附件。

## 运行控制与上下文

```bash
kotto --credentials-file ~/.config/kotto/credentials.json run '分析项目' --max-rounds 12 --max-tool-calls 64 --timeout 300
kotto --credentials-file ~/.config/kotto/credentials.json run '持续处理任务' --interactive
```

交互模式接受 `/steer 补充要求` 和 `/cancel`。补充要求按顺序在下一轮生效，不重跑已执行的工具。Ctrl-C 会取消并清理。

`--max-total-tokens` 按服务报告的累计用量阻止后续执行，可能在当前请求完成后超过阈值，不是硬计费上限。价格未知时不估算费用。`--max-rounds` 限制 Agent 主循环轮次；历史摘要可能额外调用模型，计入总时间与已报告的 token 用量。

根目录 `AGENTS.md` 适用于全工作区；子目录规则仅对相关路径生效。新的或变化的规则在编辑前需要进入上下文。规则不覆盖用户的明确要求，文件和工具结果不获得更高指令优先级。

`--context-window` 默认 64000，`--context-reserve` 默认 4096，使用保守的 UTF-8 字节估计，**不是精确 tokenizer**。历史过长时由模型分段摘要，保留全部用户要求原文、近期完整工具交换及原始会话记录。必需内容仍超限或摘要失败时明确报错，不静默删约束。摘要可能遗漏事实，原始记录仍可查；恢复时还需核验实际文件状态。

## 扩展与 Skill

```bash
kotto --credentials-file ~/.config/kotto/credentials.json run '调用 echo 工具' --extension examples/echo_extension.py
kotto command hello world --extension examples/echo_extension.py
kotto --credentials-file ~/.config/kotto/credentials.json run '按指南检查项目' --skill /外部路径/SKILL.md
```

Python 扩展是**可信宿主代码**，显式启用即允许它在当前进程运行；不自动扫描、下载或执行仓库插件，也不提供插件沙箱。注册的工具经过统一参数、权限与日志入口；插件本身仍可执行任意 Python，不能依靠工具策略隔离恶意插件。

`activate(host)` 可注册 `Tool`、命令和事件订阅，返回可选的同步清理函数。Skill 是文本指南，显式启用后作用于本次运行，并计入上下文预算。单份指南上限 64 KiB。

Python 嵌入示例：

```python
import asyncio
import os
from contextlib import aclosing
from kotto import Settings, create_agent

async def main():
    settings = Settings.from_env(os.environ)
    async with create_agent(settings) as agent:
        async with aclosing(agent.run('搜索仓库入口')) as events:
            async for event in events:
                print(event.kind, event.data)

asyncio.run(main())
```

提前结束消费时请使用 `aclosing` 或显式 `await stream.aclose()`，让运行立即清理；仅停止读取却不关闭，无法被即时识别，最终仍受总超时约束。更多示例见 [examples](examples/README.md)，接口约定见 [架构说明](docs/architecture.md)。

## 结构

```text
src/kotto/
  contracts/    # 运行事件与工具结果
  model/        # DeepSeek 流式适配及公开 Protocol
  runtime/      # Agent 循环、取消、队列与预算
  tools/        # 校验、权限、只读工具、原子编辑与宿主命令
  context/      # 作用域规则、预算与非破坏性历史压缩
  session/      # 单写入者日志、恢复与附件
  extensions/   # 显式可信插件与 Skill
  cli/          # 终端输入、JSON 事件和交互控制
  config.py     # 外部配置与密钥脱敏
  bootstrap.py  # 依赖组装及 create_agent
specs/          # 十项规格、状态与验收证据
```

## 测试与验收

```bash
python -m pip install '.[dev]'
python -m unittest discover -s tests -v
ruff check .
ruff format --check .
python -m build
```

默认测试离线运行，包含本地 HTTP 流、权限、冲突、进程清理、恢复、压缩和扩展测试；不需要 Key。CI 覆盖 macOS/Linux 与 Python 3.11/3.12。真实模型验收需显式运行 [evals/run_live.py](evals/run_live.py)，会产生模型调用费用，使用合成临时仓库并独立运行检查，不修改用户项目。

JSON 为逐行事件，区分文本增量、完整模型消息、工具结果和运行结束。`run_end.reason` 表示运行状态；**模型回答结束并不证明用户任务已通过验收**。应结合真实测试退出码与文件检查。

退出码：0 成功；1 模型/运行/预算错误；2 配置错误或 doctor 未就绪；130 用户取消。

首版不包含 Web UI、多 Agent、长期记忆、插件市场、Windows 支持或生产部署。没有发布 PyPI。代码与技术文档遵循 [MIT](LICENSE)，品牌视觉遵循 [BRAND.md](BRAND.md)。
