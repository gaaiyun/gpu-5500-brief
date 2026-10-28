#!/usr/bin/env bash
# Commit this run's generated data to main: publish_data.sh "<message>" <path>...
# The run's files are the newest copies, so when main has moved they are laid over the new main and pushed again.
# Merging pretty-printed JSON hunk by hunk would conflict or mix two runs' output.
set -euo pipefail
message="$1"; shift
git add -- "$@"
git diff --cached --quiet && exit 0
git commit -q -m "$message"
for attempt in 1 2 3; do
  git push -q origin HEAD:main && exit 0
  echo "main moved; replaying this run's data on top (attempt $attempt)"
  saved=$(mktemp -d)
  for path in "$@"; do
    [ -e "$path" ] && mkdir -p "$saved/$(dirname "$path")" && cp -r "$path" "$saved/$(dirname "$path")/"
  done
  git fetch -q origin main
  git reset -q --hard origin/main
  cp -r "$saved/." .
  git add -- "$@"
  git diff --cached --quiet && exit 0
  git commit -q -m "$message"
done
exit 1
