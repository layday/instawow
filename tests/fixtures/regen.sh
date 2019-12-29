#!/usr/bin/env nix-shell
#!nix-shell -i bash -p httpie jq

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"


echo '[20338,23350,306085,288981,322865,2398,326516,326009,333072,345144]' \
    | http post https://addons-ecs.forgesvc.net/api/v2/addon -b \
    | jq -r \
    > "$DIR"/curse-post-addon_all.json

http get https://api.mmoui.com/v3/game/WOW/filelist.json -b \
    | jq -r '.[] | select(.UID == "13188") | [.]' \
    > "$DIR"/wowi-get-filelist.json
http get https://api.mmoui.com/v3/game/WOW/filedetails/13188.json -b \
    | jq -r \
    > "$DIR"/wowi-get-filedetails.json

http get 'https://www.tukui.org/api.php?ui=tukui' -b \
    | jq -r \
    > "$DIR"/tukui-get-ui_tukui.json
http get 'https://www.tukui.org/api.php?addon=1' -b \
    | jq -r \
    > "$DIR"/tukui-get-addon.json
http get 'https://www.tukui.org/api.php?classic-addon=1' -b \
    | jq -r \
    > "$DIR"/tukui-get-classic-addon.json

http get https://raw.githubusercontent.com/layday/instawow-data/data/master-catalogue-v1.json -b \
    | jq -r \
    > "$DIR"/master-catalogue.json
