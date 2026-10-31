# 0.1.0 验收与发布就绪记录

日期：2026-10-31。代码范围：F01–F10。本地运行平台：macOS / Python 3.11。Windows 不在支持范围，未发布 PyPI 或部署服务。

## 本地质量门

- 离线 unittest：54 个方法通过，覆盖本地 HTTP、权限、编辑冲突、进程组清理、恢复、上下文、SDK 和扩展。
- Ruff 0.15.9：check 与 format --check 通过。
- build 1.4.0：wheel 与 sdist 构建通过。
- 独立虚拟环境从 wheel 安装成功；pip check 无依赖冲突。
- 真实验收使用安装后的 wheel，清除源目录 PYTHONPATH，避免源码掩盖打包问题。
- 凭据保存在项目外，显式载入；公开内容在提交前按实际 Key 做字节扫描，不包含凭据。

## 真实 DeepSeek 验收

[结构化报告](live-report.json) 记录五个案例：阅读定位、修复 bug、恢复会话、添加函数、扩展 SDK 调用。全部 PASS。

- 阅读要求精确引用 maths.py:1，得到 MAGIC_NUMBER=73129。
- bug 夹具原有 unittest 确实失败，模型使用 hash-checked patch 修复后，模型命令与独立重跑均通过。
- 恢复同一会话后代码字节不变；恢复不能跨工作区或扩大原授权，CLI 与 SDK 均有回归保护。
- 新增 multiply，独立检查正数、负数、零，同时保留 add、原测试与项目规则。
- 真模型调用显式启用的 echo 扩展，并返回指定结果。
- 本次请求模型标识 deepseek-flash，官方当前对应 Flash 4.1；合计报告用量 25239 tokens，耗时 18.62 秒。这是单次合成案例证据，不是未来表现或性能保证。

## 集成阶段修正

RED 后修复：重复 provider call ID 的顺序关联；会话目录符号链接；非有限预算；持久化运行边界；SDK 的工作区与原授权绑定。新/变化的路径规则在写入前需刷新，外部 JSON 凭据仅显式加载且要求私有权限。

这些修正与代码格式收口均归入 F10，不改写之前公开提交。

## 远端 CI

[GitHub CI](https://github.com/jimmyfenwick/kotto/actions/workflows/ci.yml) 为 macOS/Linux × Python 3.11/3.12 矩阵，包含离线测试、Ruff、构建和干净 wheel 安装。实际运行结果以最终提交关联的 GitHub checks 为准；提交后核对所有作业成功，才向用户报告完成。

## 实际边界

宿主 shell 和 Python 插件具有用户权限，不提供操作系统沙箱；文本摘要不能替代原始证据；token 预算不是硬计费限制；服务别名会变化。消费者提前停止需关闭事件流。品牌素材不属于代码 MIT 许可。
