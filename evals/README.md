# 真实任务验收

离线测试不等于供应商验证。本目录脚本显式调用真实 DeepSeek，并在自动清理的合成临时仓库中运行宿主命令，会产生模型调用费用。

```bash
python evals/run_live.py --live --credentials-file ~/.config/kotto/credentials.json --output /tmp/kotto-live-report.json
```

使用已安装的 wheel 验证时加 `--installed`，防止源目录 PYTHONPATH 掩盖打包缺陷。

案例包括：搜索/阅读与精确行号引用；修复真实失败测试；恢复会话且不修改文件；增加 multiply 并独立验证正数、负数、零及原有测试；模型调用真实扩展工具。脚本检查测试和项目规则未被修改，读取实际退出码，只有全部独立检查通过才生成 PASS 报告。

凭据只来自外部显式文件，报告只记录合成案例、模型标识、状态、用量及耗时，不保存 Key 或用户代码。版本化的最终报告见 docs/verification/live-report.json；它是某次实测，不保证未来模型表现不变。
