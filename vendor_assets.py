"""Put Bootstrap and Bootstrap Icons into app/static/vendor/.

    python vendor_assets.py                  download
    python vendor_assets.py --from C:\\dl     copy from a folder you filled by hand
    python vendor_assets.py --check          report what is present

Assets are vendored rather than loaded from a CDN so the application works
offline and behind a proxy that blocks jsdelivr — which is the normal case on
a managed laptop. Manual placement is a first-class path for the same reason
it is in docs/MODEL_INSTALL_GUIDE.md: the download may simply be refused.

The application renders correctly without any of this. personalos.css styles
the whole shell on its own; Bootstrap adds its component library and the icon
font replaces the single-letter placeholders in the sidebar.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "app" / "static" / "vendor"

BOOTSTRAP_VERSION = "5.3.3"
ICONS_VERSION = "1.11.3"

ASSETS = [
    {
        "target": VENDOR / "bootstrap" / "bootstrap.min.css",
        "url": f"https://cdn.jsdelivr.net/npm/bootstrap@{BOOTSTRAP_VERSION}/dist/css/bootstrap.min.css",
        "min_bytes": 150_000,
        "required": True,
    },
    {
        "target": VENDOR / "bootstrap" / "bootstrap.bundle.min.js",
        "url": f"https://cdn.jsdelivr.net/npm/bootstrap@{BOOTSTRAP_VERSION}/dist/js/bootstrap.bundle.min.js",
        "min_bytes": 60_000,
        "required": False,
    },
    {
        "target": VENDOR / "bootstrap-icons" / "bootstrap-icons.css",
        "url": f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{ICONS_VERSION}/font/bootstrap-icons.min.css",
        "min_bytes": 60_000,
        "required": False,
    },
    {
        "target": VENDOR / "bootstrap-icons" / "fonts" / "bootstrap-icons.woff2",
        "url": f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{ICONS_VERSION}/font/fonts/bootstrap-icons.woff2",
        "min_bytes": 80_000,
        "required": False,
    },
    {
        "target": VENDOR / "bootstrap-icons" / "fonts" / "bootstrap-icons.woff",
        "url": f"https://cdn.jsdelivr.net/npm/bootstrap-icons@{ICONS_VERSION}/font/fonts/bootstrap-icons.woff",
        "min_bytes": 100_000,
        "required": False,
    },
]


def report():
    print(f"Vendor directory: {VENDOR}\n")
    complete = True
    for asset in ASSETS:
        target = asset["target"]
        if target.exists():
            size = target.stat().st_size
            ok = size >= asset["min_bytes"]
            state = f"{size:,} bytes" + ("" if ok else "  ← TRUNCATED")
            complete = complete and (ok or not asset["required"])
        else:
            state = "missing"
            complete = complete and not asset["required"]
        print(f"  {'[ok] ' if target.exists() else '[  ] '}"
              f"{target.relative_to(ROOT)}  {state}")
    return complete


def place(asset, data):
    target = asset["target"]
    if len(data) < asset["min_bytes"]:
        raise ValueError(
            f"{target.name} is {len(data):,} bytes, expected at least "
            f"{asset['min_bytes']:,} — the transfer was truncated"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"  wrote {target.relative_to(ROOT)}  ({len(data):,} bytes)")


def download():
    try:
        import requests
    except ImportError:
        print("requests is not installed — `pip install -r requirements.txt`", file=sys.stderr)
        return 1

    failures = []
    for asset in ASSETS:
        try:
            response = requests.get(asset["url"], timeout=60)
            response.raise_for_status()
            place(asset, response.content)
        except Exception as exc:
            failures.append((asset, exc))
            print(f"  failed {asset['target'].name}: {exc}")

    if failures:
        print("\nSome assets could not be downloaded. This is expected behind a")
        print("proxy that blocks jsdelivr. Fetch them from a machine that can")
        print("reach the internet, put them in one folder, and run:\n")
        print("    python vendor_assets.py --from <that folder>\n")
        print("Files to fetch:")
        for asset, _exc in failures:
            print(f"    {asset['url']}")
        return 1 if any(a["required"] for a, _ in failures) else 0

    print("\nDone. Restart PersonalOS to pick the assets up.")
    return 0


def copy_from(source_dir):
    source_dir = Path(source_dir).expanduser()
    if not source_dir.is_dir():
        print(f"Not a directory: {source_dir}", file=sys.stderr)
        return 1

    missing = []
    for asset in ASSETS:
        # Accept either the CDN filename or the target filename, since a manual
        # download of bootstrap-icons.min.css keeps the .min in its name.
        candidates = [
            source_dir / asset["target"].name,
            source_dir / asset["url"].rsplit("/", 1)[-1],
        ]
        found = next((c for c in candidates if c.exists()), None)
        if found is None:
            missing.append(asset)
            continue
        place(asset, found.read_bytes())

    for asset in missing:
        level = "required" if asset["required"] else "optional"
        print(f"  not found ({level}): {asset['url'].rsplit('/', 1)[-1]}")

    return 1 if any(a["required"] for a in missing) else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Vendor Bootstrap into app/static/vendor/.")
    parser.add_argument("--from", dest="source", help="copy from a folder instead of downloading")
    parser.add_argument("--check", action="store_true", help="report what is present and stop")
    args = parser.parse_args(argv)

    if args.check:
        return 0 if report() else 1

    code = copy_from(args.source) if args.source else download()
    print()
    report()
    return code


if __name__ == "__main__":
    sys.exit(main())
