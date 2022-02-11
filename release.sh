#!/bin/bash


old=$1
new=$2
if [[ -z "$old" || -z "$new" ]] ; then
  echo "Usage: $0 oldversion newversion"
  exit 1
fi
reldate=$(date +%Y-%m-%d)
echo "Updating changelog"
sed -ibk -e "s/Unreleased/$new  $reldate/" CHANGELOG.md

echo "updating README and pyproject.toml"
sed -ibk -e "s/==$old/==$new/" README.md  
sed -ibk -e "s/\"$old\"/\"$new\"/" pyproject.toml

black rspace_client
"committing and tagging"
git ci -am "Release $new"
git tag -m"$new" -a "v$new" 

echo "now run poetry shell, poetry build && poetry publish and push to Github"
