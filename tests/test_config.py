"""Tests for project_creator.config."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, call, patch

import pytest
import yaml

import project_creator.config as cfg_module
from project_creator.config import (
    _deep_merge,
    DEFAULT_GFA_DOMAIN,
    get_domain_allow_list,
    is_domain_allowed,
    load_config,
    save_config,
    validate_config,
    _DEFAULT_CONFIG,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect CONFIG_DIR / CONFIG_PATH to a temporary directory."""
    config_dir = tmp_path / ".config" / "project_creator"
    config_path = config_dir / "config.yaml"
    monkeypatch.setattr(cfg_module, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(cfg_module, "CONFIG_PATH", config_path)
    return config_dir, config_path


def _make_yaml(data: Dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        yaml.dump(data, fh)


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge:
    def test_returns_defaults_when_base_empty(self):
        defaults = {"a": 1, "b": {"c": 2}}
        result = _deep_merge({}, defaults)
        assert result == defaults

    def test_base_values_override_defaults(self):
        result = _deep_merge({"a": 99}, {"a": 1, "b": 2})
        assert result["a"] == 99
        assert result["b"] == 2  # missing key filled from defaults

    def test_nested_merge(self):
        base = {"templates": {"proposal": "MY_ID"}}
        defaults = {"templates": {"proposal": "", "purchase_summary_sow": ""}}
        result = _deep_merge(base, defaults)
        assert result["templates"]["proposal"] == "MY_ID"
        assert result["templates"]["purchase_summary_sow"] == ""

    def test_extra_keys_in_base_preserved(self):
        result = _deep_merge({"extra": "value"}, {"a": 1})
        assert result["extra"] == "value"

    def test_non_dict_value_not_recursed(self):
        # Base has a plain value where defaults has a dict — base wins
        result = _deep_merge({"k": "flat"}, {"k": {"nested": 1}})
        assert result["k"] == "flat"

    def test_does_not_mutate_defaults(self):
        defaults = {"a": {"b": 1}}
        _deep_merge({"a": {"b": 2}}, defaults)
        assert defaults["a"]["b"] == 1  # unchanged


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------

class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_config):
        _, config_path = tmp_config
        assert not config_path.exists()
        config = load_config()
        assert config["templates"]["gfa_form_url"] == "https://red.ht/gfa"
        assert config["search_root_id"] == ""
        assert config["gfa"]["domain"] == DEFAULT_GFA_DOMAIN
        assert config["gfa"]["domain_allow_list"] == ["redhat.com"]

    def test_loads_and_merges_existing_file(self, tmp_config):
        _, config_path = tmp_config
        _make_yaml({"templates": {"proposal": "PROP_ID"}}, config_path)
        config = load_config()
        assert config["templates"]["proposal"] == "PROP_ID"
        # Missing keys are merged from defaults
        assert config["templates"]["purchase_summary_sow"] == ""
        assert config["templates"]["cu_calculator"] == ""

    def test_handles_empty_yaml_file(self, tmp_config):
        _, config_path = tmp_config
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("")  # empty file → yaml.safe_load returns None
        config = load_config()
        assert config == _deep_merge({}, _DEFAULT_CONFIG)

    def test_handles_full_valid_config(self, tmp_config):
        _, config_path = tmp_config
        data = {
            "templates": {
                "proposal": "P1",
                "purchase_summary_sow": "S1",
                "gfa_form_url": "https://custom.url/gfa",
            },
            "search_root_id": "ROOT123",
        }
        _make_yaml(data, config_path)
        config = load_config()
        assert config["templates"]["proposal"] == "P1"
        assert config["search_root_id"] == "ROOT123"

    def test_permission_error_propagates(self, tmp_config):
        _, config_path = tmp_config
        _make_yaml({"templates": {}}, config_path)
        config_path.chmod(0o000)
        try:
            with pytest.raises(PermissionError):
                load_config()
        finally:
            config_path.chmod(0o644)  # restore so tmp_path cleanup works


# ---------------------------------------------------------------------------
# save_config
# ---------------------------------------------------------------------------

class TestSaveConfig:
    def test_writes_yaml_to_path(self, tmp_config):
        config_dir, config_path = tmp_config
        data = {"templates": {"proposal": "ABC"}, "search_root_id": ""}
        save_config(data)
        assert config_path.exists()
        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["templates"]["proposal"] == "ABC"

    def test_creates_parent_directory(self, tmp_config):
        config_dir, config_path = tmp_config
        assert not config_dir.exists()
        save_config({"templates": {"proposal": "X"}, "search_root_id": ""})
        assert config_dir.exists()

    def test_sets_directory_permissions(self, tmp_config):
        config_dir, _ = tmp_config
        save_config({"templates": {}, "search_root_id": ""})
        mode = stat.S_IMODE(config_dir.stat().st_mode)
        assert mode == 0o700

    def test_sets_file_permissions(self, tmp_config):
        _, config_path = tmp_config
        save_config({"templates": {}, "search_root_id": ""})
        mode = stat.S_IMODE(config_path.stat().st_mode)
        assert mode == 0o600

    def test_overwrites_existing_file(self, tmp_config):
        _, config_path = tmp_config
        save_config({"templates": {"proposal": "FIRST"}, "search_root_id": ""})
        save_config({"templates": {"proposal": "SECOND"}, "search_root_id": ""})
        loaded = yaml.safe_load(config_path.read_text())
        assert loaded["templates"]["proposal"] == "SECOND"

    def test_permission_error_on_directory_creation(self, tmp_config, tmp_path):
        """When the parent directory cannot be created, an OSError is raised."""
        config_dir, config_path = tmp_config
        with patch.object(config_dir.__class__, "mkdir", side_effect=PermissionError("denied")):
            with pytest.raises(PermissionError):
                save_config({"templates": {}, "search_root_id": ""})


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------

class TestValidateConfig:
    def _full_config(self) -> Dict[str, Any]:
        return {
            "templates": {
                "proposal": "PROP",
                "purchase_summary_sow": "SOW",
            },
            "search_root_id": "",
        }

    def test_valid_config_returns_no_errors(self):
        assert validate_config(self._full_config()) == []

    def test_missing_proposal_returns_error(self):
        config = self._full_config()
        config["templates"]["proposal"] = ""
        errors = validate_config(config)
        assert any("templates.proposal" in e for e in errors)

    def test_missing_sow_returns_error(self):
        config = self._full_config()
        config["templates"]["purchase_summary_sow"] = ""
        errors = validate_config(config)
        assert any("templates.purchase_summary_sow" in e for e in errors)

    def test_both_missing_returns_two_errors(self):
        config = self._full_config()
        config["templates"]["proposal"] = ""
        config["templates"]["purchase_summary_sow"] = ""
        errors = validate_config(config)
        assert len(errors) == 2

    def test_missing_templates_key_entirely(self):
        errors = validate_config({})
        assert len(errors) == 2

    def test_none_value_treated_as_missing(self):
        config = self._full_config()
        config["templates"]["proposal"] = None
        errors = validate_config(config)
        assert any("templates.proposal" in e for e in errors)

    def test_whitespace_only_treated_as_set(self):
        """Whitespace-only string is truthy in Python — no error expected."""
        config = self._full_config()
        config["templates"]["proposal"] = "   "
        errors = validate_config(config)
        # Whitespace is truthy, so no error is raised (documents current behaviour)
        assert not any("templates.proposal" in e for e in errors)

    def test_invalid_gfa_form_url(self):
        config = self._full_config()
        config["templates"]["gfa_form_url"] = "http://evil.example/form"
        errors = validate_config(config)
        assert any("gfa_form_url" in e for e in errors)

    def test_domain_not_in_allow_list(self):
        config = self._full_config()
        config["gfa"] = {
            "domain": "example.com",
            "domain_allow_list": ["redhat.com"],
        }
        errors = validate_config(config)
        assert any("domain_allow_list" in e for e in errors)

    def test_world_writable_modifications_dir(self, tmp_path):
        config = self._full_config()
        mod_dir = tmp_path / "mods"
        mod_dir.mkdir()
        mod_dir.chmod(0o777)
        config["modifications_dir"] = str(mod_dir)
        errors = validate_config(config)
        assert any("world-writable" in e or "group-" in e for e in errors)

    def test_get_domain_allow_list_defaults(self):
        assert get_domain_allow_list({}) == ["redhat.com"]

    def test_is_domain_allowed(self):
        config = {"gfa": {"domain_allow_list": ["redhat.com", "ibm.com"]}}
        assert is_domain_allowed(config, "ibm.com")
        assert not is_domain_allowed(config, "example.com")
