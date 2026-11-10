"""Formular-Bearbeitung von Konfigurationsdateien (INI/gitconfig/TOML, JSON, YAML)."""

from __future__ import annotations

import json

import pytest
import yaml

from yaleno_wizard.core.formats import (
    IniDocument, TreeDocument, detect_format, parse_document, read_text, toggle_bool,
)

GITCONFIG = """# meine Einstellungen
[user]
\tname = Alice
\temail = alice@example.org
[core]
\teditor = vim
\tautocrlf = false
"""


def test_detect_format():
    assert detect_format("settings.json", "{}") == "json"
    assert detect_format("config.yml", "a: 1") == "yaml"
    assert detect_format(".gitconfig", "") == "ini"
    assert detect_format("kwinrc", "[Windows]\nBorderless=true\n") == "ini"
    assert detect_format("starship.toml", "") == "ini"
    assert detect_format("notes", "Einkaufsliste:\n- Milch\n- Brot\n") == "text"
    assert detect_format(".bashrc", "if [ -f x ]; then\n  . x\nfi\nexport PATH\n") == "text"


def test_ini_roundtrip_unchanged():
    doc = IniDocument.parse(GITCONFIG)
    assert doc.render() == GITCONFIG
    assert [(f.section, f.key, f.value) for f in doc.fields] == [
        ("user", "name", "Alice"), ("user", "email", "alice@example.org"),
        ("core", "editor", "vim"), ("core", "autocrlf", "false"),
    ]
    assert doc.fields[3].kind == "bool"


def test_ini_edit_keeps_comments_and_style():
    doc = IniDocument.parse(GITCONFIG)
    name = doc.fields[0]
    doc.set_value(name.id, "Bob")
    doc.remove(doc.fields[2].id)          # editor
    doc.add("core", "pager", "less")
    doc.add("alias", "st", "status")      # neuer Abschnitt
    out = doc.render()
    assert out.startswith("# meine Einstellungen\n[user]\n\tname = Bob\n")
    assert "editor" not in out
    assert "\tautocrlf = false\n\tpager = less\n" in out
    assert out.endswith("[alias]\n\tst = status\n")
    with pytest.raises(ValueError):
        doc.set_value(name.id, "zwei\nzeilen")
    with pytest.raises(ValueError):
        doc.add("core", "", "x")


def test_ini_without_sections_and_crlf():
    text = "a=1\r\nb = hallo welt\r\n"
    doc = IniDocument.parse(text)
    assert doc.sections() == [""]
    doc.set_value(doc.fields[1].id, "neu")
    assert doc.render() == "a=1\r\nb = neu\r\n"


def test_kde_keys_and_toml():
    doc = IniDocument.parse("[General]\nName[$e]=$HOME/x\nColorScheme=Breeze\n")
    assert [f.key for f in doc.fields] == ["Name[$e]", "ColorScheme"]
    toml = IniDocument.parse('[character]\nsuccess_symbol = "[➜](bold green)"\nadd_newline = true\n')
    assert toml.fields[0].value == '"[➜](bold green)"'
    assert toml.sections() == ["character"]


def test_toggle_bool_keeps_style():
    assert toggle_bool("true", False) == "false"
    assert toggle_bool("Yes", False) == "No"
    assert toggle_bool("OFF", True) == "ON"
    assert toggle_bool('"false"', True) == '"true"'
    assert toggle_bool("true", True) == "true"


def test_json_edit_scalars():
    text = json.dumps({"editor": {"fontSize": 12, "wordWrap": False, "theme": "dark"},
                       "list": [1, "x"], "empty": None}, indent=4)
    doc = parse_document("json", text)
    assert isinstance(doc, TreeDocument)
    keys = {(f.section, f.key): f for f in doc.fields}
    doc.set_value(keys[("editor", "fontSize")].id, "14")
    doc.set_value(keys[("editor", "wordWrap")].id, "true")
    doc.set_value(keys[("list", "[1]")].id, "y")
    with pytest.raises(ValueError):
        doc.set_value(keys[("editor", "fontSize")].id, "groß")
    out = doc.render()
    assert json.loads(out) == {"editor": {"fontSize": 14, "wordWrap": True, "theme": "dark"},
                               "list": [1, "y"], "empty": None}
    assert '\n    "editor"' in out  # Einrückung übernommen


def test_yaml_edit_keeps_order():
    doc = parse_document("yaml", "zeta: 1\nalpha:\n  on: true\n  name: x\n")
    f = next(f for f in doc.fields if f.key == "name")
    doc.set_value(f.id, "y")
    out = doc.render()
    assert out.index("zeta") < out.index("alpha")
    assert yaml.safe_load(out)["alpha"]["name"] == "y"


def test_broken_json_falls_back():
    assert parse_document("json", "{kaputt") is None


def test_read_text_rejects_binary(tmp_path):
    p = tmp_path / "bin"
    p.write_bytes(b"\x00\x01\x02")
    assert read_text(p) is None
    t = tmp_path / "t.ini"
    t.write_text("a=1")
    assert read_text(t) == "a=1"
