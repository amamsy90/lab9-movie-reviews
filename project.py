"""Shared, export-time project configuration used by all three services."""
import json
from pathlib import Path
import re

PROJECT = json.loads(Path(__file__).with_name("project.json").read_text())
CATEGORIES = tuple(PROJECT["categories"])
if (len(CATEGORIES) != 3 or len(set(CATEGORIES)) != 3
        or any(not re.fullmatch(r"[a-z][a-z_]*", label) for label in CATEGORIES)):
    raise ValueError("A project must have exactly three distinct category labels.")
