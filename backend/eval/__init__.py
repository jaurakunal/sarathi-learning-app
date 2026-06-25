"""LLM evaluation harness for Sarathi.

Compare alternative models against the Sonnet 4.6 baseline on the digest task,
using real user engagement as the golden dataset.

Modules:
- dataset: clone live user data + build reusable eval dataset in DDB
- runner: execute digest with a candidate model on the eval set
- judge: LLM-as-judge scoring with engagement alignment check
- report: tabular comparison across runs
"""

from __future__ import annotations
