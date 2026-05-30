.DEFAULT_GOAL := help

.PHONY: help scope-guard docs-guard draft-guard limit-guard line-guard default-symbol-guard scheme-manual-lines-guard learning-page-guard entry verify smoke round round-smoke

help:
	@echo "Available targets:"
	@echo "  make entry       # 固定入口检查"
	@echo "  make scope-guard # 交付范围守护（禁止非本地交付口径回流）"
	@echo "  make docs-guard  # 文档治理守护（文档入口与关键段落一致性）"
	@echo "  make draft-guard # 人工修正草稿本地保存守护检查"
	@echo "  make limit-guard # 回测涨跌停比例 limit_pct 链路守护检查"
	@echo "  make line-guard  # 手工划线链路守护检查"
	@echo "  make default-symbol-guard # 默认标的与初始时间窗守护检查"
	@echo "  make scheme-manual-lines-guard # 分析方案 manual_lines / manual_line_style 链路守护检查"
	@echo "  make learning-page-guard # 学习教程独立页面守护检查"
	@echo "  make verify      # scope-guard + docs-guard + draft-guard + limit-guard + line-guard + default-symbol-guard + scheme-manual-lines-guard + learning-page-guard + pytest + lint + build + diff --check"
	@echo "  make smoke       # 本地 smoke"
	@echo "  make round       # 入口检查 + 一键验证"
	@echo "  make round-smoke # 入口检查 + 一键验证 + smoke"

entry:
	./scripts/check_goal_entry.sh

scope-guard:
	./scripts/check_scope_guard.sh

docs-guard:
	./scripts/check_docs_guard.sh

draft-guard:
	./scripts/check_workspace_draft_guard.sh

limit-guard:
	./scripts/check_limit_pct_guard.sh

line-guard:
	./scripts/check_line_drawing_guard.sh

default-symbol-guard:
	./scripts/check_default_symbol_guard.sh

scheme-manual-lines-guard:
	./scripts/check_scheme_manual_lines_guard.sh

learning-page-guard:
	./scripts/check_learning_page_guard.sh

verify:
	./scripts/verify_local.sh

smoke:
	./scripts/smoke_local.sh

round:
	./scripts/run_goal_round.sh

round-smoke:
	./scripts/run_goal_round.sh --with-smoke
