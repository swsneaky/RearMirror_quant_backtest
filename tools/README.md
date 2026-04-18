# tools/

工具与草稿脚本收敛目录。

根据 docs/rulebooks/engineering_constraints.md §5.3 路径纪律:
- 一次性排障脚本、临时验证脚本、开发辅助工具应收敛到此目录
- 根目录仅允许长期正式入口和长期说明文件
- 新增临时运行脚本不得默认落在仓库根目录

长期规则总入口仍为 `AI_CONTEXT.md`；详细文件治理规则已拆分到 `docs/rulebooks/engineering_constraints.md`。

已收敛脚本 (canonical 入口):
- `tools/qa_neutralize_run.py` — QA 沙盒 neutralize 验证
- `tools/formal_neutralize_run.py` — 正式路径 neutralize 验证

根目录兼容 shim (仅过渡保留，不是默认落点):
- `_qa_neutralize_run.py` → 转发到 `tools/qa_neutralize_run.py`
- `_formal_neutralize_run.py` → 转发到 `tools/formal_neutralize_run.py`

后续新增同类脚本的默认落点: 本目录 (`tools/`)

校验工具:
- `tools/validate_three_files.py` — 校验 `HANDOFF.md` / `WORKLOG.md` / `AI_CONTEXT.md` 的基础结构是否仍满足当前协作协议；凡是覆写 `HANDOFF.md` 或调整三大文件规则，正式流转前都必须运行并通过

尚在根目录的历史脚本 (未来治理轮次处理):
- `test_duckdb.py`
- `test_full_pipeline.py`
