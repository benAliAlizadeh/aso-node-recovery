from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_validate_release_mounts_checkout_read_only():
    text = (ROOT / "scripts" / "asoctl.sh").read_text(encoding="utf-8")
    assert '-v "$PROJECT_ROOT:/source:ro"' in text
    assert 'python "/source/scripts/${validator}"' in text
    assert "COPY tests" not in (ROOT / "docker" / "prod.Dockerfile").read_text(encoding="utf-8")

def test_registry_ui_recovers_untrusted_host_key_for_add_and_edit():
    text = (ROOT / "app" / "bot" / "registry_ui.py").read_text(encoding="utf-8")
    assert "_is_untrusted_ssh_host_key_error" in text
    assert 'resume_stage="node_ssh_secret"' in text
    assert 'resume_stage="node_ssh_edit_secret"' in text
    assert "Trust this fingerprint" in text
