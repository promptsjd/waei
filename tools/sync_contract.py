"""Refresh or check the external compatibility mirrors of packaged resources."""

import argparse
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    package = root / "src/pyscenedetect_demo/contract"
    external = root.parent / "editing-contract"
    if not external.is_dir():
        print("Standalone checkout: external compatibility folder is not present")
        return 0
    mismatches = []
    for source in package.rglob("*"):
        if source.suffix not in {".json", ".md"}:
            continue
        target = external / source.relative_to(package)
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            mismatches.append(str(source.relative_to(package)))
            if not args.check:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    if mismatches and args.check:
        print("Contract mirrors differ: " + ", ".join(mismatches))
        return 1
    print(f"Contract mirrors {'checked' if args.check else 'updated'} ({len(mismatches)} differences)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
