from pathlib import Path


def test_phase1_does_not_implement_later_phase_business_modules() -> None:
    root = Path(__file__).resolve().parents[1] / "app"
    reserved_packages = [
        "database",
        "providers",
        "monitoring",
        "deployment",
        "workers",
        "bot",
    ]

    for package in reserved_packages:
        python_files = sorted((root / package).glob("*.py"))
        assert [path.name for path in python_files] == ["__init__.py"]
