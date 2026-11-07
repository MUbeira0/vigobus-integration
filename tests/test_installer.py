from custom_components.vigobus import installer


def test_installs_everything_into_an_empty_config(tmp_path):
    changed = installer.install_assets(tmp_path)

    assert sorted(changed["blueprints"]) == sorted(
        p.name for p in installer.BLUEPRINT_SOURCE.glob("*.yaml")
    )
    assert sorted(changed["sentences"]) == ["en", "es", "gl"]
    assert (tmp_path / "blueprints/automation/vigobus/bus_arriving_notify.yaml").is_file()
    assert (tmp_path / "custom_sentences/es/vigobus.yaml").is_file()


def test_second_run_changes_nothing(tmp_path):
    installer.install_assets(tmp_path)
    assert installer.install_assets(tmp_path) == {"blueprints": [], "sentences": []}


def test_refreshes_our_outdated_files(tmp_path):
    installer.install_assets(tmp_path)
    blueprint = tmp_path / "blueprints/automation/vigobus/bus_arriving_notify.yaml"
    blueprint.write_text("# old version from github.com/MUbeira0/vigobus-integration\n", encoding="utf-8")

    changed = installer.install_assets(tmp_path)

    assert changed["blueprints"] == ["bus_arriving_notify.yaml"]
    assert "old version" not in blueprint.read_text(encoding="utf-8")


def test_never_overwrites_a_customised_file(tmp_path):
    installer.install_assets(tmp_path)
    blueprint = tmp_path / "blueprints/automation/vigobus/leave_now_notify.yaml"
    sentences = tmp_path / "custom_sentences/es/vigobus.yaml"
    blueprint.write_text("blueprint: {name: mine}\n", encoding="utf-8")
    sentences.write_text("language: es\n", encoding="utf-8")

    changed = installer.install_assets(tmp_path)

    assert changed == {"blueprints": [], "sentences": []}
    assert blueprint.read_text(encoding="utf-8") == "blueprint: {name: mine}\n"
    assert sentences.read_text(encoding="utf-8") == "language: es\n"
