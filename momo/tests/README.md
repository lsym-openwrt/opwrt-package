# momo 订阅转换测试套件

端到端自测 + 回归验证：`run_tests.py` 通过 `harness/` 中的 stub（sing-box / curl / jsonfilter / Clash API）驱动转换器，验证 13 种订阅格式的解析与生成。

由于原始测试样本（`fixtures/`）可能包含真实机场节点与凭据信息，**未随本仓库分发**。

使用方法：

1. 自行将订阅样本放置到 `tests/fixtures/`（建议先用虚构节点脱敏）
2. 运行：

   ```bash
   python3 tests/run_tests.py
   ```
