#! /usr/bin/env nix-shell
#! nix-shell -i bash -p httpie jq

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" > /dev/null 2>&1 && pwd)"


echo '{"modIds": [2382, 20338, 23350, 288981, 322865, 2398, 326516, 333072, 402180]}' \
    | http post https://api.curseforge.com/v1/mods \
        x-api-key:$CFCORE_API_KEY -b \
    | jq -r \
    > "$DIR"/curse-addon--all.json
http get https://api.curseforge.com/v1/mods/20338/files \
        x-api-key:$CFCORE_API_KEY -b \
    | jq -r \
    > "$DIR"/curse-addon-files.json
http get https://api.curseforge.com/v1/mods/20338/files/3657564/changelog \
        x-api-key:$CFCORE_API_KEY -b \
    | jq -r \
    > "$DIR"/curse-addon-changelog.json


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
    | jq -r '.[] | select(.id == "2") | [.]' \
    > "$DIR"/tukui-classic-addons.json
http get 'https://www.tukui.org/api.php?classic-wotlk-addons' -b \
    | jq -r '.[] | select(.id == "2") | [.]' \
    > "$DIR"/tukui-classic-wotlk-addons.json


http get 'https://api.github.com/repos/nebularg/PackagerTest' -b \
    | jq -r \
    > "$DIR"/github-repo-release-json.json
http get 'https://api.github.com/repos/nebularg/PackagerTest/releases?per_page=1' -b \
    | jq -r \
    > "$DIR"/github-release-release-json.json
http --follow get 'https://github.com/nebularg/PackagerTest/releases/download/v1.9.7/release.json' -b \
    | jq -r \
    > "$DIR"/github-release-release-json-release-json.json
http get 'https://api.github.com/repos/p3lim-wow/Molinari' -b \
    | jq -r \
    > "$DIR"/github-repo-molinari.json
http get 'https://api.github.com/repos/p3lim-wow/Molinari/releases?per_page=1' -b \
    | jq -r \
    > "$DIR"/github-release-molinari.json
http --follow get 'https://github.com/p3lim-wow/Molinari/releases/download/90200.82-Release/release.json' -b \
    | jq -r \
    > "$DIR"/github-release-molinari-release-json.json
http get 'https://api.github.com/repos/ketho-wow/RaidFadeMore' -b \
    | jq -r \
    > "$DIR"/github-repo-no-release-json.json
http get 'https://api.github.com/repos/ketho-wow/RaidFadeMore/releases?per_page=1' -b \
    | jq -r \
    > "$DIR"/github-release-no-release-json.json
http get 'https://api.github.com/repos/AdiAddons/AdiBags' -b \
    | jq -r \
    > "$DIR"/github-repo-no-releases.json
http get 'https://api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19' -b \
    | jq -r \
    > "$DIR"/github-release-no-assets.json


http get https://raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v7.compact.json -b \
    | jq -r \
    > "$DIR"/base-catalogue-v7.compact.json


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


echo '{
  "addons": [
    {
      "id": "WqKQQEKx",
      "name": "Molinari",
      "authors": [
        "p3lim"
      ],
      "website_url": "https://addons.wago.io/addons/molinari",
      "thumbnail": null,
      "matched_release": {
        "id": "kwX3VMdb",
        "label": "90207.84-Release",
        "patch": "9.2.7",
        "created_at": "2022-09-21T20:39:36.000000Z",
        "link": "https://addons.wago.io/external/download/abc?link=def"
      },
      "modules": {
        "Molinari": {
          "hash": "2da096db5769138b5428a068343cddf3"
        }
      },
      "cf": "20338",
      "wowi": "13188",
      "wago": "WqKQQEKx",
      "recent_releases": {
        "stable": {
          "id": "RQ0OkG6W",
          "label": "90207.85-Release",
          "patch": "9.2.7",
          "created_at": "2022-10-03T20:15:36.000000Z",
          "link": "https://addons.wago.io/external/download/abc?link=def"
        }
      }
    }
  ]
}' \
    | jq -r \
    > "$DIR"/wago-match-addons.json
