#!/bin/bash

set -euo pipefail

new=${1:-}
if [[ -z "$new" ]] ; then
  echo "Usage: $0 newversion"
  exit 1
fi
reldate=$(date +%Y-%m-%d)

echo "Updating changelog"
sed -ibk -e "s/## Unreleased/## $new  $reldate/" CHANGELOG.md

echo "Bumping pyproject.toml version"
poetry version "$new"

poetry run ruff format rspace_client examples

echo "Committing and tagging"
git commit -am "Release $new"
git tag -m "$new" -a "v$new"

echo "Now run: git push && git push --tags"
echo "Pushing the tag triggers .github/workflows/release.yml, which builds and publishes to PyPI."
