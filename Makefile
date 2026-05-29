.PHONY: install uninstall help

help:
	@echo "Usage:"
	@echo "  make install     Install d3b-dewrangle CLI and dependencies"
	@echo "  make uninstall   Remove d3b-dewrangle (pip uninstall d3b-dewrangle)"

install:
	@pip install -r requirements.txt
	@pip install -e .
	@echo "✅ Installed d3b-dewrangle"
	@echo "   Run: d3b-dewrangle --help"

uninstall:
	@pip uninstall -y d3b-dewrangle
	@echo "🗑️  Removed d3b-dewrangle"
