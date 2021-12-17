#! /usr/bin/env nix-shell
#! nix-shell -i bash -p httpie jq

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"


echo '[2382,20338,23350,288981,322865,2398,326516,333072,402180]' \
    | http post https://addons-ecs.forgesvc.net/api/v2/addon -b \
    | jq -r \
    > "$DIR"/curse-addon--all.json
http get https://addons-ecs.forgesvc.net/api/v2/addon/20338/files -b \
    | jq -r \
    > "$DIR"/curse-addon-files.json
http get https://addons-ecs.forgesvc.net/api/v2/addon/20338/file/3475338/changelog -b \
    > "$DIR"/curse-addon-changelog.txt


http get https://api.mmoui.com/v3/game/WOW/filelist.json -b \
    | jq -r '.[] | select(.UID == "13188") | [.]' \
    > "$DIR"/wowi-filelist.json
http get https://api.mmoui.com/v3/game/WOW/filedetails/13188.json -b \
    | jq -r \
    > "$DIR"/wowi-filedetails.json


http get 'https://www.tukui.org/api.php?ui=tukui' -b \
    | jq -r \
    > "$DIR"/tukui-ui--tukui.json
http get 'https://www.tukui.org/api.php?ui=elvui' -b \
    | jq -r \
    > "$DIR"/tukui-ui--elvui.json
http get 'https://www.tukui.org/api.php?addons' -b \
    | jq -r '.[] | select(.id == "1") | [.]' \
    > "$DIR"/tukui-retail-addons.json
http get 'https://www.tukui.org/api.php?classic-addons' -b \
    | jq -r '.[] | select(.id == "1") | [.]' \
    > "$DIR"/tukui-classic-addons.json
http get 'https://www.tukui.org/api.php?classic-tbc-addons' -b \
    | jq -r '.[] | select(.id == "1") | [.]' \
    > "$DIR"/tukui-classic-tbc-addons.json


http get 'https://api.github.com/repos/nebularg/PackagerTest' -b \
    | jq -r \
    > "$DIR"/github-repo-release-json.json
http get 'https://api.github.com/repos/nebularg/PackagerTest/releases/latest' -b \
    | jq -r \
    > "$DIR"/github-release-release-json.json
http --follow get 'https://github.com/nebularg/PackagerTest/releases/download/v1.9.6/release.json' -b \
    | jq -r \
    > "$DIR"/github-release-release-json-release-json.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras' -b \
    | jq -r \
    > "$DIR"/github-repo-legacy-lib-and-nolib.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/latest' -b \
    | jq -r \
    > "$DIR"/github-release-legacy-lib-and-nolib.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.1.0' -b \
    | jq -r \
    > "$DIR"/github-release-legacy-lib-and-nolib-older-version.json
http get 'https://api.github.com/repos/p3lim-wow/Molinari' -b \
    | jq -r \
    > "$DIR"/github-repo-legacy-retail-and-classic.json
http get 'https://api.github.com/repos/p3lim-wow/Molinari/releases/latest' -b \
    | jq -r \
    > "$DIR"/github-release-legacy-retail-and-classic.json
http get 'https://api.github.com/repos/AdiAddons/AdiBags' -b \
    | jq -r \
    > "$DIR"/github-repo-no-releases.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19' -b \
    | jq -r \
    > "$DIR"/github-release-no-assets.json


http get https://raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v5.compact.json -b \
    | jq -r \
    > "$DIR"/base-catalogue-v5.compact.json


echo '{
  "device_code": "3584d83530557fdd1f46af8289938c8ef79f9dc5",
  "user_code": "WDJB-MJHT",
  "verification_uri": "https://github.com/login/device",
  "expires_in": 900,
  "interval": 5
}' \
    | jq -r \
    > "$DIR"/github-oauth-login-device-code.json
echo '{
  "access_token": "gho_16C7e42F292c6912E7710c838347Ae178B4a",
  "token_type": "bearer",
  "scope": "repo,gist"
}' \
    | jq -r \
    > "$DIR"/github-oauth-login-access-token.json
