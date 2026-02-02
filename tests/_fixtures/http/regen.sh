#! /usr/bin/env nix-shell
#! nix-shell -i bash -p curl jq

set -ex

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"


curl -X POST https://api.curseforge.com/v1/mods \
    -H 'Content-Type: application/json' \
    -H "x-api-key: $INSTAWOW_ACCESS_TOKENS_CFCORE" \
    -d '{"modIds": [2382, 13592, 326516, 402180, 1299675]}' \
    | jq -r \
    > "$DIR"/curse-addon--all.json
curl 'https://api.curseforge.com/v1/mods/search?gameId=1&slug=masque' \
    -H "x-api-key: $INSTAWOW_ACCESS_TOKENS_CFCORE" \
    | jq -r \
    > "$DIR"/curse-addon-slug-search.json
curl https://api.curseforge.com/v1/mods/13592/files \
    -H "x-api-key: $INSTAWOW_ACCESS_TOKENS_CFCORE" \
    | jq -r \
    > "$DIR"/curse-addon-files.json
curl https://api.curseforge.com/v1/mods/13592/files/7373575 \
    -H "x-api-key: $INSTAWOW_ACCESS_TOKENS_CFCORE" \
    | jq -r \
    > "$DIR"/curse-addon-file-7373575.json
curl https://api.curseforge.com/v1/mods/13592/files/7398127 \
    -H "x-api-key: $INSTAWOW_ACCESS_TOKENS_CFCORE" \
    | jq -r \
    > "$DIR"/curse-addon-file-7398127.json
curl https://api.curseforge.com/v1/mods/13592/files/7398127/changelog \
    -H "x-api-key: $INSTAWOW_ACCESS_TOKENS_CFCORE" \
    | jq -r \
    > "$DIR"/curse-addon-changelog.json


curl https://api.mmoui.com/v3/game/WOW/filelist.json \
    | jq -r '.[] | select(.UID == "12097") | [.]' \
    > "$DIR"/wowi-filelist.json
curl https://api.mmoui.com/v3/game/WOW/filedetails/12097.json \
    | jq -r \
    > "$DIR"/wowi-filedetails.json


curl https://api.tukui.org/v1/addon/tukui \
    | jq -r \
    > "$DIR"/tukui-ui--tukui.json
curl https://api.tukui.org/v1/addon/elvui \
    | jq -r \
    > "$DIR"/tukui-ui--elvui.json


curl 'https://api.github.com/repos/nebularg/PackagerTest' \
    | jq -r \
    > "$DIR"/github-repo-release-json.json
curl 'https://api.github.com/repos/nebularg/PackagerTest/releases?per_page=1' \
    | jq -r \
    > "$DIR"/github-release-release-json.json
curl 'https://github.com/nebularg/PackagerTest/releases/download/v1.9.7/release.json' \
    -L \
    | jq -r \
    > "$DIR"/github-release-release-json-release-json.json
curl 'https://api.github.com/repos/sfx-wow/masque' \
    | jq -r \
    > "$DIR"/github-repo-masque.json
curl 'https://api.github.com/repos/sfx-wow/masque/releases?per_page=10' \
    | jq -r \
    > "$DIR"/github-release-masque.json
curl $(
    jq -r \
        '.[] | select(.prerelease == false) | .assets[] | select(.name == "release.json") | .browser_download_url' \
        "$DIR"/github-release-masque.json
    ) \
    -L \
    | jq -r \
    > "$DIR"/github-release-masque-release-json.json
curl 'https://api.github.com/repos/28/NoteworthyII' \
    | jq -r \
    > "$DIR"/github-repo-no-release-json.json
curl 'https://api.github.com/repos/28/NoteworthyII/releases?per_page=1' \
    | jq -r \
    > "$DIR"/github-release-no-release-json.json
curl 'https://api.github.com/repos/AdiAddons/AdiBags' \
    | jq -r \
    > "$DIR"/github-repo-no-releases.json
curl 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19' \
    | jq -r \
    > "$DIR"/github-release-no-assets.json


curl https://raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v8.compact.json \
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
