#!/bin/bash
# Prepares a release on main: updates the changelog and version, commits and
# tags. Pushing the tag publishes to PyPI (.github/workflows/release.yml), which
# only accepts a tag on main, so this must run on main, not on a PR branch.

set -euo pipefail

new=${1:-}
if [[ -z "$new" ]] ; then
  echo "Usage: $0 newversion"
  exit 1
fi
reldate=$(date +%Y-%m-%d)

branch=$(git rev-parse --abbrev-ref HEAD)
if [[ "$branch" != main ]] ; then
  echo "Run this on main, not $branch. PRs are squash-merged, so a tag made on"
  echo "another branch never lands on main and release.yml would refuse it."
  exit 1
fi
if [[ -n "$(git status --porcelain)" ]] ; then
  echo "The working tree has uncommitted changes. Commit or stash them first."
  exit 1
fi
git fetch --no-tags origin main
if [[ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]] ; then
  echo "Local main differs from origin/main. Pull or push first."
  exit 1
fi

echo "Updating changelog"
headings=$(grep -c '^## Unreleased$' CHANGELOG.md || true)
if [[ "$headings" != 1 ]] ; then
  echo "CHANGELOG.md must have exactly one '## Unreleased' heading, found $headings"
  exit 1
fi
sed -i.bak -e "s/^## Unreleased$/## $new  $reldate/" CHANGELOG.md
rm CHANGELOG.md.bak

echo "Bumping pyproject.toml version"
poetry version "$new"

poetry run ruff format rspace_client examples

echo "Committing and tagging"
git commit -am "Release $new"
git tag -m "$new" -a "v$new"

echo "Now run: git push origin main && git push origin v$new"
echo "Pushing the tag triggers .github/workflows/release.yml, which builds and publishes to PyPI."
