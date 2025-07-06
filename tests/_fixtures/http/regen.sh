#! /usr/bin/env nix-shell
#! nix-shell -i bash -p httpie jq

set -ex

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"


echo '{"modIds": [2382, 13592, 326516, 402180, 1299675]}' \
    | http post https://api.curseforge.com/v1/mods \
        x-api-key:$INSTAWOW_ACCESS_TOKENS_CFCORE -b \
    | jq -r \
    > "$DIR"/curse-addon--all.json
http get 'https://api.curseforge.com/v1/mods/search?gameId=1&slug=masque' \
        x-api-key:$INSTAWOW_ACCESS_TOKENS_CFCORE -b \
    | jq -r \
    > "$DIR"/curse-addon-slug-search.json
http get https://api.curseforge.com/v1/mods/13592/files \
        x-api-key:$INSTAWOW_ACCESS_TOKENS_CFCORE -b \
    | jq -r \
    > "$DIR"/curse-addon-files.json
http get https://api.curseforge.com/v1/mods/13592/files/6454541 \
        x-api-key:$INSTAWOW_ACCESS_TOKENS_CFCORE -b \
    | jq -r \
    > "$DIR"/curse-addon-file-6454541.json
http get https://api.curseforge.com/v1/mods/13592/files/5810397 \
        x-api-key:$INSTAWOW_ACCESS_TOKENS_CFCORE -b \
    | jq -r \
    > "$DIR"/curse-addon-file-5810397.json
http get https://api.curseforge.com/v1/mods/13592/files/6454541/changelog \
        x-api-key:$INSTAWOW_ACCESS_TOKENS_CFCORE -b \
    | jq -r \
    > "$DIR"/curse-addon-changelog.json


http get https://api.mmoui.com/v3/game/WOW/filelist.json -b \
    | jq -r '.[] | select(.UID == "12097") | [.]' \
    > "$DIR"/wowi-filelist.json
http get https://api.mmoui.com/v3/game/WOW/filedetails/12097.json -b \
    | jq -r \
    > "$DIR"/wowi-filedetails.json


http get 'https://api.tukui.org/v1/addon/tukui' -b \
    | jq -r \
    > "$DIR"/tukui-ui--tukui.json
http get 'https://api.tukui.org/v1/addon/elvui' -b \
    | jq -r \
    > "$DIR"/tukui-ui--elvui.json


http get 'https://api.github.com/repos/nebularg/PackagerTest' -b \
    | jq -r \
    > "$DIR"/github-repo-release-json.json
http get 'https://api.github.com/repos/nebularg/PackagerTest/releases?per_page=1' -b \
    | jq -r \
    > "$DIR"/github-release-release-json.json
http --follow get 'https://github.com/nebularg/PackagerTest/releases/download/v1.9.7/release.json' -b \
    | jq -r \
    > "$DIR"/github-release-release-json-release-json.json
http get 'https://api.github.com/repos/sfx-wow/masque' -b \
    | jq -r \
    > "$DIR"/github-repo-masque.json
http get 'https://api.github.com/repos/sfx-wow/masque/releases?per_page=10' -b \
    | jq -r \
    > "$DIR"/github-release-masque.json
http --follow get $(
    jq -r \
        '.[] | select(.prerelease == false) | .assets[] | select(.name == "release.json") | .browser_download_url' \
        "$DIR"/github-release-masque.json
) -b \
    | jq -r \
    > "$DIR"/github-release-masque-release-json.json
http get 'https://api.github.com/repos/28/NoteworthyII' -b \
    | jq -r \
    > "$DIR"/github-repo-no-release-json.json
http get 'https://api.github.com/repos/28/NoteworthyII/releases?per_page=1' -b \
    | jq -r \
    > "$DIR"/github-release-no-release-json.json
http get 'https://api.github.com/repos/AdiAddons/AdiBags' -b \
    | jq -r \
    > "$DIR"/github-repo-no-releases.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19' -b \
    | jq -r \
    > "$DIR"/github-release-no-assets.json


http get https://raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v8.compact.json -b \
    | jq -r \
    > "$DIR"/base-catalogue-v8.compact.json


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
