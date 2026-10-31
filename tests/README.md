# 离线回归测试

```bash
python -m unittest discover -s tests -v
```

当前 54 个测试方法覆盖 CLI 与外部凭据、HTTP/SSE、只读工具、路径与权限、原子编辑、命令退出码、超时与取消、单写入者恢复、预算与 steering、上下文压缩、扩展和 SDK。测试使用本地 HTTP 与合成临时文件，不需要真实 Key。

真实服务不属于默认测试，显式入口为 evals/run_live.py。已安装 wheel 的真实验收报告在 docs/verification/live-report.json。

tests/fixtures 预留给需要文件化的后续夹具；当前夹具由测试在系统临时目录生成并自动清理。
