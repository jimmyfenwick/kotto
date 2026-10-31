# 示例

安装项目后运行：

- `python examples/embed.py`：从环境变量读取配置，以 Python SDK 启动只读 Agent。需要真实 Key。
- `kotto command hello world --extension examples/echo_extension.py`：不调用模型，验证显式插件命令。
- `kotto run "调用 echo 工具" --extension examples/echo_extension.py`：模型使用插件工具，需要真实 Key。

Python 扩展拥有宿主进程权限，只加载你信任的文件。工具权限默认只读；注册为 write/shell 的工具仍受统一授权入口控制。SDK 提前停止读取时使用 contextlib.aclosing，退出时 await agent.aclose()；async with create_agent(...) 会自动清理。
