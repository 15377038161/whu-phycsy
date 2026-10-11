"""Layout regression tests for the shared CSS and base template."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def css() -> str:
    return (Path(__file__).resolve().parent.parent / "static" / "quantum-platform.css").read_text(
        encoding="utf-8"
    )


def test_diag_form_styles_are_scoped_to_diag_page(css):
    """Diagnostic form card styling must not leak into the topbar icon buttons."""
    assert ".diag-page .diag-form{" in css
    # The padded/bordered diagnostic form rule must be scoped.
    assert ".diag-page .diag-form{margin:0;padding:1rem;" in css


def test_small_screen_header_is_compact(css):
    """At 390px-class viewports the header must not overflow the viewport."""
    assert "@media(max-width:720px){" in css
    assert ".site-header{gap:10px;padding-left:12px;padding-right:12px}" in css
    assert ".site-header .primary-nav{gap:10px}" in css
    assert ".site-header .primary-nav a{font-size:10px}" in css
    assert ".site-header .user-actions{gap:4px}" in css
    assert ".site-header .icon-button{padding:4px}" in css


def test_no_viewport_overflow_hidden_workaround(css):
    """The layout fix must not hide overflow on the whole page."""
    assert "html{overflow:hidden" not in css.replace(" ", "")
    assert "body{overflow:hidden" not in css.replace(" ", "")
    assert "body{overflow-x:hidden" not in css.replace(" ", "")
