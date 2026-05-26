"""
app/agents/json_utils.py

Robust JSON parser for Claude responses.
Claude sometimes returns:
  - Markdown fences  (```json ... ```)
  - // line comments
  - /* block comments */
  - Trailing commas  ({"a":1,})
  - Extra whitespace / BOM
"""
from __future__ import annotations

import json
import re


def _strip_fences(text: str) -> str:
    text = text.strip()
    # Remove leading ```json or ``` fence
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    # Remove trailing ``` fence
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _strip_comments(text: str) -> str:
    # Remove /* ... */ block comments
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # Remove // line comments (but not inside strings)
    result = []
    in_string = False
    escape = False
    i = 0
    while i < len(text):
        c = text[i]
        if escape:
            result.append(c)
            escape = False
            i += 1
            continue
        if c == "\\" and in_string:
            result.append(c)
            escape = True
            i += 1
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            i += 1
            continue
        if not in_string and c == "/" and i + 1 < len(text) and text[i + 1] == "/":
            # skip until end of line
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        result.append(c)
        i += 1
    return "".join(result)


def _fix_trailing_commas(text: str) -> str:
    return re.sub(r",\s*([}\]])", r"\1", text)


def _recover_truncated_json(text: str) -> str:
    """
    Close any unclosed strings, arrays, or objects that result from Claude
    hitting its max_tokens limit mid-response.
    """
    stack: list[str] = []
    in_string = False
    escape_next = False

    for c in text:
        if escape_next:
            escape_next = False
            continue
        if c == "\\" and in_string:
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if not in_string:
            if c in "{[":
                stack.append(c)
            elif c in "}]":
                if stack:
                    stack.pop()

    closers = {"{": "}", "[": "]"}
    suffix = ""
    if in_string:
        suffix += '"'
    while stack:
        suffix += closers[stack.pop()]
    return text + suffix


def _escape_control_chars_in_strings(text: str) -> str:
    """
    Escape literal newlines, carriage returns and tabs that appear inside
    JSON string values.  Claude sometimes puts raw newlines in strings like
    schema_markup_snippet which makes json.loads raise 'Unterminated string'.
    """
    result = []
    in_string = False
    escape_next = False
    for c in text:
        if escape_next:
            result.append(c)
            escape_next = False
            continue
        if c == "\\" and in_string:
            result.append(c)
            escape_next = True
            continue
        if c == '"':
            in_string = not in_string
            result.append(c)
            continue
        if in_string:
            if c == "\n":
                result.append("\\n")
            elif c == "\r":
                result.append("\\r")
            elif c == "\t":
                result.append("\\t")
            else:
                result.append(c)
        else:
            result.append(c)
    return "".join(result)


def safe_json_parse_report(raw: str, agent: str) -> tuple[dict, str | None]:
    """
    Parse Claude JSON output. Returns (parsed_dict, error_message).
    On failure returns ({}, error) instead of raising — keeps the pipeline alive.
    """
    try:
        return safe_json_parse(raw), None
    except json.JSONDecodeError as exc:
        return {}, f"{agent}: JSON parse failed – {exc}"


def safe_json_parse(raw: str) -> dict:
    """
    Parse a JSON string returned by Claude, tolerating all common issues:
      - Markdown fences
      - // and /* */ comments
      - Trailing commas
      - Literal newlines / tabs inside string values  (unterminated string)
    Raises json.JSONDecodeError only if every recovery attempt fails.
    """
    # Attempt 1 — raw as-is
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Attempt 2 — strip markdown fences
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Attempt 3 — escape literal control chars inside strings (fixes "Unterminated string")
    ctrl_fixed = _escape_control_chars_in_strings(cleaned)
    try:
        return json.loads(ctrl_fixed)
    except json.JSONDecodeError:
        pass

    # Attempt 4 — strip // and /* */ comments
    no_comments = _strip_comments(ctrl_fixed)
    try:
        return json.loads(no_comments)
    except json.JSONDecodeError:
        pass

    # Attempt 5 — fix trailing commas before } or ]
    fixed = _fix_trailing_commas(no_comments)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Attempt 6 — extract the first { ... } block if there is surrounding text
    match = re.search(r"\{.*\}", fixed, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    # Attempt 7 — recover truncated JSON (token limit hit mid-response)
    recovered = _recover_truncated_json(fixed)
    recovered = _fix_trailing_commas(recovered)
    try:
        return json.loads(recovered)
    except json.JSONDecodeError:
        pass

    # Final: re-raise with a clear message
    return json.loads(fixed)
