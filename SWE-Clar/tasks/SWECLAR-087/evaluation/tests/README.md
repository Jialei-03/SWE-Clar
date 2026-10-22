# Real workbook evaluation

The six gates create actual XLSX fixtures, reopen saved files to check cell values, formulas and formatting, observe callback execution and its input state, and compare copied output bytes. No source workbook is distributed. Python, pytest and openpyxl 3.1.5 belong to the evaluator environment. Set SWECLAR_PROJECT_DIR/SWECLAR_LOG_DIR and run the official verifier; missing openpyxl is reported as infrastructure failure.
