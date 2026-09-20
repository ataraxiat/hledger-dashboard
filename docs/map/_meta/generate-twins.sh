#!/bin/sh
# Regenerate the catalog's twins. CLAUDE.md is the only hand-edited entry file;
# the others are byte-identical copies for tools that look for those names.
#
#   sh docs/map/_meta/generate-twins.sh
#
# Invariant 9: generated indexes are rebuilt by script, never hand-edited. If
# these files ever differ, this script is the one that is right.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
for twin in AGENTS.md routing.md; do
  cp "$here/CLAUDE.md" "$here/$twin"
  echo "regenerated $here/$twin"
done
