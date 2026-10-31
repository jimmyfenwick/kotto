# F01 · 工程首发与可安装 CLI

## 目标与用户结果

开发者能安装扣仔，查看版本，并在不联网、不泄露凭据的前提下检查配置。

受影响用户：本地使用扣仔的开发者及嵌入方。依赖：无。当前状态见 [实施状态](status.json)，本文不重复维护状态。

## 范围与非目标

范围：打包入口、python -m kotto、--version、doctor、配置解析、基础回归测试；首个提交同时包含全部十项规格与现有骨架。

非目标：不接入真实模型，不输出伪造 Agent 回答，不创建缺乏实现的 chat/run 子命令。

## 主流程

安装本地包 → 查看帮助或版本 → 执行 doctor → 返回可读文本或 JSON 检查报告。

## 错误与边界

缺少 Key 或模型属于未就绪，doctor 返回 2；配置格式非法返回 2；未知参数由 CLI 明确拒绝。缺少可选配置时使用文档中的默认值。

## 数据、接口与安全约束

CLI：kotto --version；kotto doctor [--json]。配置前缀 KOTTO_：BASE_URL、MODEL、API_KEY、WORKSPACE。支持 DEEPSEEK_API_KEY 作为兼容回退，默认模型 deepseek-flash、地址 https://api.deepseek.com。Key 不出现在 repr、stdout、stderr 或 JSON 中。无参数显示帮助。

## 验收条件

- F01-AC1：在临时虚拟环境安装后，kotto 与 python -m kotto 的版本相同。
- F01-AC2：doctor 在无凭据时不访问网络，输出未配置状态并返回 2。
- F01-AC3：提供合法地址、模型、Key 后返回 0；只说明配置齐全，不声称远程认证成功。
- F01-AC4：输入带 URL 用户信息、查询串或非 HTTP(S) 地址时拒绝，错误文字不回显敏感值。
- F01-AC5：测试放入唯一假 Key，所有输出均不得包含该 Key；路径不存在时 doctor 返回未就绪。

验收按每条前置条件建立测试夹具，触发所述事件并断言实际输出、状态及副作用；仅“没有抛异常”不足以通过。正常路径和错误路径至少各有一条集成测试，外部服务另用显式 smoke。

## 实施与验证

预期影响：pyproject.toml、src/kotto/__main__.py、cli/main.py、config.py、tests/test_cli.py。

复验命令（实际执行结果见 specs/status.json 所引用的验收记录）：

```text
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_cli.py' -v
```

测试驱动：先运行因缺失能力而失败的聚焦验收，再实现并通过；提交前运行全量回归及必要打包检查。

## 提交边界

一个功能点完成一次提交，提交信息：

```text
feat(F01): bootstrap installable CLI and ten-feature specifications
```

本次提交需包含实现、测试、必要文档及状态证据；推送后核验远端 HEAD 等于本地提交。未通过验收不提前标记 DONE，不用仅写规格的提交冒充功能完成。修复在提交前合并到同一切片；如已推送后发现缺陷，先报告对提交次数的影响，不改写公开历史。

## 风险、假设与开放项

本机默认 Git 身份与目标账号不同，采用仓库级身份；不修改全局 Git 配置。

负责人：当前开发协作，由用户裁定模型服务、许可及改变首版范围的取舍。事实来源：用户本次最多十个功能点、每项提交 GitHub 的要求，以及 [项目架构](../docs/architecture.md)。设计中的协议与平台支持在实现时核验，本文不代替真实兼容性证据。
