"""Install only the reviewed official Flutter revision; never change an existing SDK."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--github-actions", action="store_true")
    args = parser.parse_args()
    lock = json.loads((Path(__file__).resolve().parents[1] / "toolchain.lock.json").read_text(encoding="utf-8"))
    destination = args.destination.expanduser().resolve()
    if not destination.exists():
        subprocess.run([
            "git", "clone", "--depth", "1", "--branch", lock["flutter_version"],
            "--single-branch", lock["repository"], str(destination),
        ], check=True)
    revision = subprocess.check_output(["git", "-C", str(destination), "rev-parse", "HEAD"], text=True).strip()
    if revision != lock["flutter_commit"]:
        raise SystemExit("The existing Flutter SDK differs from toolchain.lock.json; it was not modified.")
    executable = destination / "bin" / ("flutter.bat" if os.name == "nt" else "flutter")
    if not executable.is_file():
        raise SystemExit("The verified SDK has no Flutter executable.")
    if args.github_actions:
        with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8") as path_file:
            path_file.write(str(executable.parent) + "\n")
    print(f"Verified official Flutter {lock['flutter_version']} at {destination}")


if __name__ == "__main__":
    main()
