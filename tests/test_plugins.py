"""Plugins: Format, Laden, Einbau in den Katalog, Verwaltung und Updates."""

from __future__ import annotations

import textwrap

import pytest

from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.core.scanner import Scanner
from yaleno_wizard.catalog.placeholders import PathMapper
from yaleno_wizard.plugins import manager
from yaleno_wizard.plugins.model import Plugin, PluginChanges, PluginError, newer, parse_version
from yaleno_wizard.plugins.registry import builtin_dir, discover, feature_enabled, find, plugins_dir
from yaleno_wizard.settings import Profile


def plugin_text(version: str = "1.0.0", pid: str = "demo", extra: str = "", **kw) -> str:
    cat_id = kw.get("cat_id", "demo-cat")
    return textwrap.dedent(f"""\
        yaleno_plugin: 1
        id: {pid}
        name: Demo
        version: {version}
        source: https://example.org/{pid}.yml
        type: catalog
        categories:
          - id: {cat_id}
            name: Demo-Programm
            items:
              - id: app
                label: App
                paths:
                  linux: ["{{CONFIG}}/demo"]
                  windows: ["{{APPDATA}}/Demo"]
                excludes: [cache]
        """) + extra


def write_local(text: str, name: str = "demo") -> None:
    d = plugins_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yml").write_text(text)


# ---------------------------------------------------------------------- Format
def test_version_compare():
    assert parse_version("1.2.0") == (1, 2)
    assert newer("1.10.0", "1.9.9")
    assert not newer("1.0", "1.0.0")
    assert newer("2.0.0-beta", "1.9")
    with pytest.raises(PluginError):
        parse_version("abc")


def test_parse_os_specific_paths():
    p = Plugin.from_text(plugin_text())
    lin = p.categories[0].to_category("linux")
    win = p.categories[0].to_category("windows")
    assert lin.items[0].paths == ("{CONFIG}/demo",)
    assert win.items[0].paths == ("{APPDATA}/Demo",)
    assert lin.items[0].excludes == ("cache",)
    assert p.summary() == "Kategorie „Demo-Programm“"


@pytest.mark.parametrize("bad, msg", [
    ("id: Demo!", "erlaubt sind"),
    ("version: x", "Versionsnummer"),
    ("source: http://example.org/x.yml", "https://"),
    ("type: script", "catalog oder feature"),
])
def test_invalid_fields(bad, msg):
    key = bad.split(":")[0]
    text = "\n".join(bad if line.startswith(key + ":") else line for line in plugin_text().splitlines())
    with pytest.raises(PluginError, match=msg):
        Plugin.from_text(text)


def test_invalid_paths_and_commands():
    with pytest.raises(PluginError, match="Platzhalter"):
        Plugin.from_text(plugin_text().replace("{CONFIG}/demo", "/etc/demo"))
    with pytest.raises(PluginError, match="unbekannter Platzhalter"):
        Plugin.from_text(plugin_text().replace("{CONFIG}/demo", "{NOPE}/demo"))
    with pytest.raises(PluginError, match=r"\.\."):
        Plugin.from_text(plugin_text().replace("{CONFIG}/demo", "{CONFIG}/../x"))
    with pytest.raises(PluginError, match="kein Yaleno-Plugin"):
        Plugin.from_text("foo: bar")
    with pytest.raises(PluginError, match="Ungültiges YAML"):
        Plugin.from_text("a: [")


def test_command_item_and_feature():
    p = Plugin.from_text(textwrap.dedent("""\
        yaleno_plugin: 1
        id: pkgs
        name: Pakete
        version: 1.0.0
        categories:
          - id: more-packages
            name: Mehr Pakete
            os: [linux]
            items:
              - id: pipx
                label: pipx
                kind: command
                backup_cmd: [pipx, list, --short]
        """))
    item = p.categories[0].to_category("linux").items[0]
    assert item.kind == "command" and item.backup_cmd == ("pipx", "list", "--short")
    assert p.categories[0].to_category("windows") is None
    assert p.commands() == ["[linux] sichern: pipx list --short", "[windows] sichern: pipx list --short"]

    f = Plugin.from_text("yaleno_plugin: 1\nid: enc\nname: V\nversion: 1.0.0\ntype: feature\nfeature: encryption\n")
    assert f.is_feature and f.feature == "encryption"
    with pytest.raises(PluginError, match="unbekannte Funktion"):
        Plugin.from_text("yaleno_plugin: 1\nid: x\nname: V\nversion: 1\ntype: feature\nfeature: magic\n")


def test_changes_flag_new_commands():
    old = Plugin.from_text(plugin_text("1.0.0"))
    new = Plugin.from_text(plugin_text("1.1.0").replace(
        "excludes: [cache]",
        "excludes: [cache]\n      - id: dump\n        label: Dump\n        kind: command\n"
        "        backup_cmd: [demo, --export]"))
    ch = PluginChanges.between(old, new)
    assert ch.new_commands and "demo --export" in ch.new_commands[0]
    assert "⚠ Neue Befehle" in ch.describe() and "1.0.0 → 1.1.0" in ch.describe()


# ---------------------------------------------------------------------- Katalog
def test_catalog_unchanged_without_enabled_plugins():
    write_local(plugin_text())
    cat = catalog_for("linux")
    assert cat.get("demo-cat") is None
    assert "prismlauncher" in {lp.id for lp in discover()}  # mitgeliefert, aber aus


def test_enabled_plugin_in_catalog_and_scanned(tmp_path, fake_home):
    write_local(plugin_text())
    prof = Profile()
    manager.set_enabled("demo", True, prof)
    cat = catalog_for("linux")
    assert cat.get("demo-cat") is not None and cat.plugins == ["demo"]
    (fake_home["CONFIG"] / "demo").mkdir()
    (fake_home["CONFIG"] / "demo" / "a.conf").write_text("x")
    (fake_home["CONFIG"] / "demo" / "cache").mkdir()
    (fake_home["CONFIG"] / "demo" / "cache" / "b").write_text("y")
    res = Scanner(PathMapper(fake_home)).scan(cat, ["demo-cat", "apps"])
    demo = [e.logical for e in res.for_category("demo-cat")]
    assert demo == ["{CONFIG}/demo/a.conf"]
    # Plugin-Kategorie hat Vorrang vor „Weitere Anwendungs-Konfiguration“
    assert not any(e.logical.startswith("{CONFIG}/demo") for e in res.for_category("apps"))


def test_collision_skips_plugin():
    p = Plugin.from_text(plugin_text(cat_id="shell"))
    cat = catalog_for("linux", plugins=[p])
    assert [c.id for c in cat.categories].count("shell") == 1
    assert "gibt es schon" in cat.plugin_errors[0]


def test_extend_existing_category():
    p = Plugin.from_text(textwrap.dedent("""\
        yaleno_plugin: 1
        id: helix
        name: Helix
        version: 1.0.0
        extend:
          dev:
            items:
              - id: helix
                label: Helix
                paths: ["{CONFIG}/helix"]
            excludes:
              vscode: ["*.log"]
        """))
    cat = catalog_for("linux", plugins=[p])
    dev = cat.get("dev")
    assert dev.item("helix").paths == ("{CONFIG}/helix",)
    assert dev.item("vscode").excludes[-1] == "*.log"
    bad = Plugin.from_text(p.text.replace("vscode:", "nope:"))
    assert "nope" in catalog_for("linux", plugins=[bad]).plugin_errors[0]


def test_builtin_prism_plugin(fake_home):
    lp = find("prismlauncher")
    assert lp and lp.ok and lp.origin == "builtin" and not lp.removable
    cat = catalog_for("linux", plugins=[lp.plugin])
    inst = fake_home["DATA"] / "PrismLauncher" / "instances" / "Vanilla" / ".minecraft"
    (inst / "saves" / "Welt").mkdir(parents=True)
    (inst / "saves" / "Welt" / "level.dat").write_text("w")
    (inst / "logs").mkdir()
    (inst / "logs" / "latest.log").write_text("l")
    (fake_home["DATA"] / "PrismLauncher" / "libraries").mkdir()
    (fake_home["DATA"] / "PrismLauncher" / "libraries" / "x.jar").write_text("j")
    (fake_home["DATA"] / "PrismLauncher" / "accounts.json").write_text("{}")
    got = sorted(e.logical for e in Scanner(PathMapper(fake_home)).scan(cat, ["games"]).entries)
    assert got == ["{DATA}/PrismLauncher/accounts.json",
                   "{DATA}/PrismLauncher/instances/Vanilla/.minecraft/saves/Welt/level.dat"]


def test_all_builtin_plugins_valid():
    files = list(builtin_dir().glob("*.yml"))
    assert files
    for f in files:
        Plugin.read(f)


def test_broken_local_plugin_reported():
    write_local("yaleno_plugin: 1\nid: kaputt\n", "kaputt")
    lp = find("kaputt")
    assert lp is not None and not lp.ok and "fehlt" in lp.error
    with pytest.raises(PluginError, match="kann nicht aktiviert"):
        manager.set_enabled("kaputt", True, Profile())


# ---------------------------------------------------------------------- Verwaltung
def test_install_from_file_enable_remove(tmp_path):
    src = tmp_path / "demo.yml"
    src.write_text(plugin_text())
    prof = Profile()
    pending = manager.prepare_source(str(src), prof)
    assert not pending.is_update and pending.changes.added_paths
    manager.install(pending, prof)
    assert (plugins_dir() / "demo.yml").exists()
    assert Profile.load().plugins_enabled == ["demo"]
    manager.set_enabled("demo", False, prof)
    assert Profile.load().plugins_enabled == []
    manager.remove("demo", prof)
    assert find("demo") is None
    with pytest.raises(PluginError, match="nur deaktiviert"):
        manager.remove("prismlauncher", prof)


def test_feature_enabled():
    write_local("yaleno_plugin: 1\nid: enc\nname: V\nversion: 1.0.0\ntype: feature\nfeature: encryption\n", "enc")
    prof = Profile()
    assert not feature_enabled("encryption", prof)
    manager.set_enabled("enc", True, prof)
    assert feature_enabled("encryption")


def test_check_and_apply_updates():
    write_local(plugin_text("1.0.0"))
    prof = Profile()
    manager.set_enabled("demo", True, prof)
    served = {"https://example.org/demo.yml": plugin_text("1.2.0")}

    def fetch(url):
        if url not in served:
            raise PluginError("404")
        return served[url]

    assert manager.update_due(prof)
    res = manager.check_updates(prof, fetch=fetch)
    assert [u.id for u in res.updates] == ["demo"]
    assert res.updates[0].pending.changes.old_version == "1.0.0"
    assert manager.known_updates() == ["demo"] and not manager.update_due(prof)
    manager.apply_update(res.updates[0], prof)
    assert find("demo").version == "1.2.0" and find("demo").enabled
    assert manager.known_updates() == []
    assert manager.check_updates(prof, fetch=fetch).updates == []

    served["https://example.org/demo.yml"] = plugin_text("9.0.0", pid="other")
    assert "anderes Plugin" in manager.check_updates(prof, fetch=fetch).errors[0]


def test_local_override_of_builtin_only_when_newer():
    text = (builtin_dir() / "prismlauncher.yml").read_text()
    write_local(text.replace("version: 1.0.0", "version: 0.9.0"), "prismlauncher")
    assert find("prismlauncher").origin == "builtin"
    write_local(text.replace("version: 1.0.0", "version: 1.5.0"), "prismlauncher")
    lp = find("prismlauncher")
    assert lp.origin == "local" and lp.has_builtin and lp.removable
    manager.remove("prismlauncher", Profile())
    assert find("prismlauncher").origin == "builtin"


def test_fetch_requires_https():
    with pytest.raises(PluginError, match="https"):
        manager.fetch_text("http://example.org/x.yml")


def test_profile_yaml_roundtrip_plugins():
    p = Profile(plugins_enabled=["a", "b"], plugins_check_updates=False)
    q = Profile.from_yaml_dict(p.to_yaml_dict())
    assert q.plugins_enabled == ["a", "b"] and q.plugins_check_updates is False


# ---------------------------------------------------------------------- Kommandozeile
def run_cli(args, answers=()):
    from yaleno_wizard.plugins.cli import main
    out: list[str] = []
    it = iter(answers)
    rc = main(args, out=out.append, ask=lambda q: next(it))
    return rc, "\n".join(out)


def test_cli_install_list_show_disable_remove(tmp_path):
    src = tmp_path / "demo.yml"
    src.write_text(plugin_text())
    rc, out = run_cli(["install", str(src)], answers=["n"])
    assert rc == 1 and find("demo") is None
    rc, out = run_cli(["install", str(src)], answers=["j"])
    assert rc == 0 and "Installiert" in out and "(aktiv)" in out
    rc, out = run_cli(["list"])
    assert "demo" in out and "aktiv" in out and "prismlauncher" in out
    rc, out = run_cli(["show", "demo"])
    assert "{CONFIG}/demo" in out
    assert run_cli(["disable", "demo"])[0] == 0 and Profile.load().plugins_enabled == []
    assert run_cli(["remove", "demo"])[0] == 0 and find("demo") is None
    rc, out = run_cli(["remove", "prismlauncher"])
    assert rc == 2 and "nur deaktiviert" in out


def test_cli_update(monkeypatch):
    write_local(plugin_text("1.0.0"))
    monkeypatch.setattr(manager, "fetch_text", lambda url: plugin_text("2.0.0"))
    rc, out = run_cli(["check"])
    assert rc == 0 and "1.0.0 → 2.0.0" in out
    rc, out = run_cli(["update", "--all", "--yes"])
    assert rc == 0 and "Aktualisiert auf 2.0.0" in out and find("demo").version == "2.0.0"


def test_main_dispatches_plugin_command(capsys):
    from yaleno_wizard.__main__ import main
    assert main(["plugin", "list"]) == 0
    assert "prismlauncher" in capsys.readouterr().out


# ---------------------------------------------------------------------- Verteilung über den Speicher
def test_distribute_via_store(tmp_path):
    from yaleno_wizard.core.store import Store
    from yaleno_wizard.plugins import distribute
    from yaleno_wizard.storage.local import LocalStorage

    store = Store(LocalStorage(str(tmp_path / "speicher")), ".")
    store.ensure_initialized()
    write_local(plugin_text("1.1.0"))
    prof = Profile()
    manager.set_enabled("demo", True, prof)
    manager.set_enabled("prismlauncher", True, prof)
    assert sorted(distribute.publish(store, ["demo", "prismlauncher"])) == ["Demo", "Prism Launcher (Minecraft)"]
    assert distribute.publish(store, ["demo"]) == []  # schon aktuell
    assert store.list_plugins() == ["demo", "prismlauncher"]

    # „anderes Gerät“: ohne lokale Plugins
    (plugins_dir() / "demo.yml").unlink()
    other = Profile()
    other.save()
    offers = {o.plugin.id: o for o in distribute.offers(store, other)}
    assert set(offers) == {"demo", "prismlauncher"}
    assert offers["prismlauncher"].enable_only and not offers["demo"].enable_only
    distribute.accept(offers["demo"], other)
    distribute.decline(offers["prismlauncher"])
    assert find("demo", other).enabled
    assert distribute.offers(store, other) == []  # abgelehnt bzw. übernommen


def test_run_sync_publishes_plugins(tmp_path, mapper, fake_home):
    from yaleno_wizard.core.reporter import Reporter
    from yaleno_wizard.core.store import Store
    from yaleno_wizard.core.sync import ConflictWinner, SyncState, plan_sync, run_sync
    from yaleno_wizard.storage.local import LocalStorage

    write_local(plugin_text())
    manager.set_enabled("demo", True, Profile())
    cat = catalog_for("linux")
    (fake_home["CONFIG"] / "demo").mkdir()
    (fake_home["CONFIG"] / "demo" / "a.conf").write_text("x")
    store = Store(LocalStorage(str(tmp_path / "speicher")), ".")
    state = SyncState(tmp_path / "state.json")
    rep = Reporter()
    plan = plan_sync(store, Scanner(mapper).scan(cat, ["demo-cat"]).entries, state, cat, mapper,
                     "linux", "pc", {"demo-cat"}, None, reporter=rep)
    run_sync(store, plan, state, cat, mapper, "linux", "pc", ConflictWinner.NEWER, rep)
    assert store.list_plugins() == ["demo"]
    assert store.load_head().categories["demo-cat"]["plugin"] == "demo"
    assert any("im Speicher abgelegt" in line for line in rep.lines)
