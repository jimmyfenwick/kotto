# 测试

使用标准库 unittest：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

当前 test_cli.py 覆盖版本与帮助、配置校验、密钥脱敏、环境变量回退、工作目录、无网络 doctor 及未知命令。真实模型尚未实现。后续按 specs 增加行为测试，默认离线，不依赖真实凭据。
