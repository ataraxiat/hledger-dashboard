import importlib
import json
from pathlib import Path


def load_app(monkeypatch, accounting: Path, ledger_file: str | None = None):
    monkeypatch.setenv("ACCOUNTING_DIR", str(accounting))
    if ledger_file is None:
        monkeypatch.delenv("LEDGER_FILE", raising=False)
    else:
        monkeypatch.setenv("LEDGER_FILE", ledger_file)
    import app
    return importlib.reload(app)


def test_config_lives_in_the_config_shelf(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    assert app.CONFIG_PATH == tmp_path / "_config" / "hledger-dashboard" / "config.json"


def test_the_journal_defaults_into_the_ledger_shelf(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    assert app.JOURNAL == tmp_path / "ledger" / "journal" / "main.journal"


def test_ledger_file_wins_when_it_is_set(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path, ledger_file=str(tmp_path / "other.journal"))
    assert app.JOURNAL == tmp_path / "other.journal"


def test_every_hledger_command_names_the_journal_and_ignores_config_files(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    assert app.hledger_cmd("bal", "expenses")[1:4] == ["-n", "-f", str(app.JOURNAL)]


def test_rules_paths_resolve_against_accounting_dir(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    assert app.from_config("ledger/import/bank.debit.csv.rules") == (
        tmp_path / "ledger" / "import" / "bank.debit.csv.rules"
    )
    assert app.from_config("/var/tmp/r.rules") == Path("/var/tmp/r.rules")


def test_the_defaults_point_into_the_new_shelves(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    assert app.CONFIG_DEFAULTS["hledger_rules_debit"] == "ledger/import/bank.debit.csv.rules"
    assert app.CONFIG_DEFAULTS["hledger_rules_savings"] == "ledger/import/bank.savings.csv.rules"


def test_txcat_dir_is_gone_from_the_config_surface(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    assert "txcat_dir" not in app.CONFIG_DEFAULTS
    assert "txcat_dir" not in app._SETTINGS_DISK_KEYS


def test_the_example_config_uses_only_known_keys(monkeypatch, tmp_path):
    app = load_app(monkeypatch, tmp_path)
    example = json.loads((Path(__file__).resolve().parent.parent / "config.example.json").read_text())
    assert set(example) <= set(app.CONFIG_DEFAULTS)
