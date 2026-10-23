"""Optional embedding facade with a deterministic lexical fallback."""

import re


def tokens(text: str) -> set[str]:
	return set(re.findall(r"[a-zA-Z0-9_-]{3,}", text.lower()))


def similarity(left: str, right: str) -> float:
	a, b = tokens(left), tokens(right)
	return len(a & b) / max(1, len(a | b))
