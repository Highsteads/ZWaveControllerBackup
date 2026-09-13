#! /usr/bin/env bash
# Filename:    run.sh
# Description: Single gate for the Z-Wave Controller Backup contract tests.
#              Exit 0 only if everything passes.
# Author:      CliveS & Claude Fable 5.1
# Date:        13-09-2026
# Version:     1.0
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/.."
SP="Z-Wave Controller Backup.indigoPlugin/Contents/Server Plugin"

echo "== pytest (core, plugin smoke, version consistency) =="
python3 -m pytest tests -q

echo
echo "== python syntax =="
PYTHONDONTWRITEBYTECODE=1 python3 -B -m py_compile "$SP/plugin.py" "$SP/controller_image.py" "$SP/plugin_utils.py"
echo "  ok"

echo
echo "== XML well-formed =="
for f in "$SP"/*.xml "Z-Wave Controller Backup.indigoPlugin/Contents/Info.plist"; do
    python3 -c "import xml.dom.minidom,sys; xml.dom.minidom.parse(sys.argv[1])" "$f"
    echo "  ok  $(basename "$f")"
done

echo
echo "== lint (errors only) =="
# Two lines on purpose: `ruff check . && echo ok` cannot fail under set -e.
python3 -m ruff check .
echo "  ok"

echo
# py_compile writes bytecode whatever -B says; sweep it out of the bundle.
find "Z-Wave Controller Backup.indigoPlugin" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

echo "All Z-Wave Controller Backup contract tests passed."
