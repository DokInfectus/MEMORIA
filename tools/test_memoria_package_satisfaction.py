#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from memoria_package_profile import build_plan
from memoria_package_satisfaction import (
    evaluate_package_satisfaction,
)


DEBIAN_13 = {
    "profile": "debian-13",
    "support": "TESTED / OFFICIALLY SUPPORTED",
    "package_manager": "apt",
}


def ok(message: str) -> None:
    print(f"OK  {message}")


def write_status(
    path: Path,
    packages: list[str],
) -> None:
    stanzas = []

    for package in packages:
        stanzas.append(
            "\n".join([
                f"Package: {package}",
                "Status: install ok installed",
                "Architecture: amd64",
            ])
        )

    path.write_text(
        "\n\n".join(stanzas) + "\n",
        encoding="utf-8",
    )


local_plan = build_plan(
    "local-ocr",
    platform_data=DEBIAN_13,
)
local_packages = list(local_plan["packages"])

combined_plan = build_plan(
    "matrix-ui+ocr",
    platform_data=DEBIAN_13,
)
combined_packages = list(combined_plan["packages"])


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)

    full = root / "full-status"
    write_status(full, local_packages)

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=full,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "SATISFIED"
    assert result["installed_count"] == len(local_packages)
    assert result["missing_count"] == 0
    ok("5/5 Local OCR packages SATISFIED")

    partial = root / "partial-status"
    write_status(partial, local_packages[:-1])

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=partial,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "PARTIAL"
    assert result["installed_count"] == len(local_packages) - 1
    assert result["missing_packages"] == [local_packages[-1]]
    ok("4/5 Local OCR packages PARTIAL")

    missing = root / "missing-status"
    write_status(missing, ["unrelated-package"])

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=missing,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "MISSING"
    assert result["installed_count"] == 0
    assert result["missing_count"] == len(local_packages)
    ok("0/5 Local OCR packages MISSING")

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=root / "does-not-exist",
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "UNKNOWN"
    assert result["read_performed"] is True
    ok("Unavailable dpkg state fails closed UNKNOWN")


    no_status = root / "missing-status-field"
    no_status.write_text(
        f"Package: {local_packages[0]}\n"
        "Architecture: amd64\n",
        encoding="utf-8",
    )

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=no_status,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "UNKNOWN"
    assert result["read_performed"] is True
    ok("Missing Status field fails closed UNKNOWN")

    duplicate = root / "duplicate-package"
    duplicate.write_text(
        "\n\n".join([
            (
                f"Package: {local_packages[0]}\n"
                "Status: install ok installed\n"
                "Architecture: amd64"
            ),
            (
                f"Package: {local_packages[0]}\n"
                "Status: install ok installed\n"
                "Architecture: amd64"
            ),
        ]) + "\n",
        encoding="utf-8",
    )

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=duplicate,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "UNKNOWN"
    assert result["read_performed"] is True
    ok("Duplicate package record fails closed UNKNOWN")

    noninstalled = root / "valid-noninstalled"
    noninstalled.write_text(
        f"Package: {local_packages[0]}\n"
        "Status: deinstall ok config-files\n"
        "Architecture: amd64\n",
        encoding="utf-8",
    )

    result = evaluate_package_satisfaction(
        "local-ocr",
        status_path=noninstalled,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "MISSING"
    assert result["installed_count"] == 0
    assert result["missing_count"] == len(local_packages)
    ok("Valid non-installed package remains MISSING")

    result = evaluate_package_satisfaction(
        "minimal",
        status_path=root / "does-not-exist",
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "NOT APPLICABLE"
    assert result["evaluated"] is False
    assert result["read_performed"] is False
    ok("Minimal is NOT APPLICABLE and unread")

    result = evaluate_package_satisfaction(
        "matrix-ui",
        status_path=root / "does-not-exist",
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "NOT APPLICABLE"
    assert result["read_performed"] is False
    ok("Matrix UI is NOT APPLICABLE and unread")

    combined = root / "combined-status"
    write_status(combined, combined_packages)

    result = evaluate_package_satisfaction(
        "matrix-ui+ocr",
        status_path=combined,
        platform_data=DEBIAN_13,
    )

    assert result["satisfaction_status"] == "SATISFIED"
    assert result["missing_count"] == 0
    ok("Matrix UI + OCR SATISFIED")


product = Path(__file__).with_name(
    "memoria_package_satisfaction.py"
).read_text(encoding="utf-8")

for forbidden in (
    "subprocess",
    "dpkg-query",
    "apt-get",
    "apt-mark",
    "os.system",
    "Popen(",
    "write_text(",
    "write_bytes(",
):
    assert forbidden not in product, forbidden

ok("Product has no process/package-manager/write boundary")

print()
print(
    "MEMORIA Package Satisfaction V0.1 "
    "Regression Test GREEN"
)
