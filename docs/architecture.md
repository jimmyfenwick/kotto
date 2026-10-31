# KOTTO 0.1 架构与接口

状态：实现说明。验收进度见 ../specs/status.json。公开实现采用单包 src 布局，独立使用 asyncio 与 httpx。

## 依赖

CLI → bootstrap.create_agent → Agent；Agent 调用 model、tools、context、session 的接口。contracts 是共享契约。模型不执行工具，日志不调度任务，终端不直接修改模型历史。插件由显式配置加载。

| 模块 | 实际文件 | 职责 |
|---|---|---|
| contracts | event.py、tool.py | ModelEvent、AgentEvent、ToolResult |
| model | gateway.py | ModelGateway Protocol、DeepSeekGateway、SSE 与错误分类 |
| runtime | agent.py、control.py | 模型/工具循环，运行状态、队列、取消、预算 |
| tools | executor.py、policy.py、editing.py、shell.py | 注册、参数校验、工作区读取、授权、原子编辑、宿主执行 |
| context | builder.py | 路径规则、不可丢弃输入、分段压缩与快照 |
| session | store.py | Journal、锁、追加写入、崩溃恢复与附件 |
| extensions | host.py | ExtensionHost、显式加载、事件、命令、文本指南 |
| cli | main.py、chat.py、run.py、sessions.py | 配置入口、终端/JSON 输出、控制与历史查看 |

早期设计中的文件名是拆分建议；当前按实际行为合并，避免只有转发作用的空文件。

## 公共接口

- Settings.from_env(mapping, credentials_file=None)：环境或显式外部文件；凭据字段不出现在 repr。
- create_agent(settings, model=None, policy=None, journal=None, extensions=(), skills=(), **limits)：返回可异步上下文管理的 Agent。
- Agent.run(prompt)：异步 AgentEvent 流，一次只允许一个活动运行。
- Agent.steer(message)、Agent.cancel()、Agent.aclose()：有序补充、取消并等待清理、关闭扩展。
- ModelGateway.stream(messages, tools=None)：异步 ModelEvent 流；完整消息只在成功的结束标记后产出。
- Tool(name, description, parameters, handler, effect='read')：异步 handler 返回可 JSON 序列化的 dict，effect 为 read/write/shell。
- ToolExecutor.execute(call_id, name, args)：结构化 ToolResult；工具执行成功不等于命令退出码为零。
- Journal(root, session_id=None)：同步上下文管理，运行时写入前持久化意图，之后持久化结果；由调用者关闭。

Tool 参数校验支持对象必需字段/额外字段限制、基础类型、枚举和整数范围；不是完整 JSON Schema 引擎。扩展作者应在 handler 内补充领域语义检查。生产代码不依赖测试替身。

## 模型与工具循环

记录用户输入 → 合并排队要求 → 组装上下文 → 流式请求 → 保存完整模型消息 → 按顺序校验与执行工具 → 保存工具结果 → 下一轮。没有工具时结束。Model finished 与 Agent run_end 是不同事件。

模型原生工具调用 ID 可以在不同轮重复，日志按消息顺序关联，不使用全历史 ID 集合错误消除新调用。受控取消会补齐未完成的工具结果为 cancelled/error，并提示检查部分副作用；进程崩溃后无法确认的调用仍需人工检查和明确确认，不自动重放。

## 权限与持久化

Policy 是应用授权，不是 OS 沙箱。文件工具检查相对路径、凭据/内部文件和符号链接逃逸；授权编辑仍可能与同权限外部进程发生竞态。SHA 检查与原子替换降低冲突风险，不承诺强隔离。新/变化的项目规则在修改前需进入上下文。

shell 模式必须显式授权，具备宿主用户权限；命令工作目录检查不限制命令访问其他目录。已知模型 Key 不进入命令环境，但这不能限制可信宿主代码主动读取其他凭据。强隔离由部署者在整个进程外提供。

Journal 文件和附件使用私有权限。锁随进程退出释放；日志只有不完整尾行可修复，中间损坏拒绝恢复。意图落盘失败时不执行工具；结果写盘失败保留不确定事实。会话不保证外部副作用恰好一次。

## 取消与上下文

运行事件队列最多 64 项，补充要求最多 32 条，每条最多 64000 字符。取消时终止状态优先于尚未消费的进度；事件消费者需显式关闭或使用 aclosing，运行总超时仍然有效。文件写入取消会等待已启动的线程结束，避免遗留后台写入。

预算包含模型轮数、工具数、总时间和已报告 token 用量；不提供硬远程计费上限。未知费用不填零。

上下文通过 UTF-8 字节估计预留输出空间，保持全部用户要求原文，近期工具调用/结果成组保留。摘要按有界历史片段生成，保留决策、证据和待办；失败不改摘要状态，不删除原始日志。规则在各自 scope 下生效，显式 Skill 作用于整次运行。

## 扩展生命周期

显式 Python 文件包含同步 activate(host)，可以返回同步 cleanup。host 支持 register_tool、register_command、subscribe；订阅器可同步或异步。订阅失败使运行明确失败，不吞异常。启用插件是对代码的信任，统一工具授权不构成 Python 插件隔离。

不自动发现插件，不下载执行第三方代码，不支持热更新。初始化失败会执行已经登记的清理；Agent.aclose 清理运行和插件。品牌资源、许可和技术文档分别维护。
