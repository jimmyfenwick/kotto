# 测试

使用标准库 unittest：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

当前 test_cli.py 覆盖版本与帮助、配置校验、密钥脱敏、环境变量回退、工作目录、无网络 doctor 及未知命令。test_model.py 和 test_chat.py 覆盖本地流式 HTTP、工具分片、错误分类和 CLI；已完成一次真实 DeepSeek 文本 smoke，证据在 specs/evidence/F02.md；真实服务不作为默认测试依赖。后续按 specs 增加行为测试，默认离线，不依赖真实凭据。
