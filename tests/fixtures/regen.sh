#!/usr/bin/env nix-shell
#!nix-shell -i bash -p httpie jq

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"


echo '[20338,23350,306085,288981,322865,2398,326516,326009,333072,345144]' \
    | http post https://addons-ecs.forgesvc.net/api/v2/addon -b \
    | jq -r \
    > "$DIR"/curse-addon--all.json
http get https://addons-ecs.forgesvc.net/api/v2/addon/20338/files -b \
    | jq -r \
    > "$DIR"/curse-addon-files.json

http get https://api.mmoui.com/v3/game/WOW/filelist.json -b \
    | jq -r '.[] | select(.UID == "13188") | [.]' \
    > "$DIR"/wowi-filelist.json
http get https://api.mmoui.com/v3/game/WOW/filedetails/13188.json -b \
    | jq -r \
    > "$DIR"/wowi-filedetails.json

http get 'https://www.tukui.org/api.php?ui=tukui' -b \
    | jq -r \
    > "$DIR"/tukui-ui--tukui.json
http get 'https://www.tukui.org/api.php?addon=1' -b \
    | jq -r \
    > "$DIR"/tukui-addon.json
http get 'https://www.tukui.org/api.php?classic-addon=1' -b \
    | jq -r \
    > "$DIR"/tukui-classic-addon.json


http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras' -b \
    | jq -r \
    > "$DIR"/github-repo-lib-and-nolib.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/latest' -b \
    | jq -r \
    > "$DIR"/github-release-lib-and-nolib.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.1.0' -b \
    | jq -r \
    > "$DIR"/github-release-lib-and-nolib-older-version.json
http get 'https://api.github.com/repos/WeakAuras/WeakAuras2' -b \
    | jq -r \
    > "$DIR"/github-repo-retail-and-classic.json
http get 'https://api.github.com/repos/WeakAuras/WeakAuras2/releases/latest' -b \
    | jq -r \
    > "$DIR"/github-release-retail-and-classic.json
http get 'https://api.github.com/repos/p3lim-wow/Molinari' -b \
    | jq -r \
    > "$DIR"/github-repo-no-releases.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19' -b \
    | jq -r \
    > "$DIR"/github-release-no-assets.json

http get https://raw.githubusercontent.com/layday/instawow-data/data/master-catalogue-v1.json -b \
    | jq -r \
    > "$DIR"/master-catalogue.json
