<script lang="ts">
  import type { Config } from "../api";
  import { fade } from "svelte/transition";
  import { activeProfile, api, profiles } from "../store";
  import ProfileView from "./ProfileView.svelte";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";

  let statusMessage = " ";
  let installedVersion: string;
  let newVersion: string | null;

  const performInitialSetup = async () => {
    ({ installed_version: installedVersion, new_version: newVersion } = await $api.getVersion());
    const profileConfigs = await Promise.allSettled(
      (await $api.listProfiles()).map(async (p) => await $api.readProfile(p))
    );
    $profiles = new Map(
      profileConfigs
        .filter((r): r is PromiseFulfilledResult<Config> => r.status === "fulfilled")
        .map(({ value }) => [value.profile, value])
    );
    $activeProfile = $profiles.keys().next().value;
  };
</script>

{#await performInitialSetup()}
  <div class="wrapper">
    <header class="section menubar" />
    <main class="section main" />
    <footer class="section statusbar">
      <div class="status">loading…</div>
    </footer>
  </div>
{:then}
  <div class="wrapper">
    <header class="section menubar">
      <ProfileSwitcher />
      <div class="instawow-version">
        <b>instawow</b><!--
        --><br />
        <span>
          {newVersion ? `${installedVersion} < ${newVersion}` : installedVersion}
        </span>
      </div>
    </header>
    <main class="section main">
      {#each [...$profiles.keys()] as profile (profile)}
        <ProfileView bind:statusMessage {profile} isActive={profile === $activeProfile} />
      {/each}
    </main>
    <footer class="section statusbar">
      <div class="status" in:fade>{statusMessage}</div>
    </footer>
  </div>
{/await}

<style lang="scss">
  @use "scss/vars";

  :global(:root) {
    --base-color: #{vars.$base-color-light};
    --base-color-tone-10: #{lighten(vars.$base-color-light, 05%)};
    --base-color-tone-20: #{rgba(vars.$inverse-color-light, 0.1)};
    --base-color-alpha-65: #{rgba(vars.$base-color-light, 0.65)};
    --inverse-color: #{vars.$inverse-color-light};
    --inverse-color-alpha-05: #{rgba(vars.$inverse-color-light, 0.05)};
    --inverse-color-alpha-10: #{rgba(vars.$inverse-color-light, 0.1)};
    --inverse-color-alpha-20: #{rgba(vars.$inverse-color-light, 0.2)};
    --inverse-color-tone-10: #{lighten(vars.$inverse-color-light, 10%)};
    --inverse-color-tone-20: #{lighten(vars.$inverse-color-light, 20%)};
    --alert-background-color: #{rgba(salmon, 0.5)};
    --dropdown-arrow: #{vars.generate-dropdown-arrow(vars.$inverse-color-light)};
  }

  @media (prefers-color-scheme: dark) {
    :global(:root) {
      --base-color: #{vars.$base-color-dark};
      --base-color-tone-10: #{darken(vars.$base-color-dark, 02%)};
      --base-color-tone-20: #{darken(vars.$base-color-dark, 10%)};
      --base-color-alpha-65: #{rgba(vars.$base-color-dark, 0.65)};
      --inverse-color: #{vars.$inverse-color-dark};
      --inverse-color-alpha-05: #{rgba(vars.$inverse-color-dark, 0.05)};
      --inverse-color-alpha-10: #{rgba(vars.$inverse-color-dark, 0.15)};
      --inverse-color-alpha-20: #{rgba(vars.$inverse-color-dark, 0.25)};
      --inverse-color-tone-10: #{darken(vars.$inverse-color-dark, 05%)};
      --inverse-color-tone-20: #{darken(vars.$inverse-color-dark, 10%)};
      --alert-background-color: #{rgba(salmon, 0.5)};
      --dropdown-arrow: #{vars.generate-dropdown-arrow(vars.$inverse-color-dark)};
    }
  }

  :global(*, *::before, *::after) {
    box-sizing: border-box;
  }

  :global(:focus) {
    outline-style: none; /* a11y - revisit */
  }

  :global(body) {
    color: var(--inverse-color);
    margin: 0;
    font-family: -apple-system, system-ui;
    overflow: hidden; // Prevent rubber banding on macOS
  }

  :global(input, button, select, textarea) {
    font: inherit;
    background-color: inherit;
    color: inherit;
  }

  :global(a) {
    text-decoration: none;
  }

  :global(menu, nav) {
    -webkit-user-select: none;
    user-select: none;
  }

  .wrapper {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }

  .section {
    padding: 0 0.8em;
  }

  .menubar {
    display: flex;
    align-items: center;
    min-height: 55px;

    .instawow-version {
      flex-grow: 1;
      text-align: right;
      font-family: vars.$mono-font-stack;
      font-size: 0.7em;

      span {
        color: var(--inverse-color-tone-10);
      }
    }
  }

  .main {
    @extend %stretch-vertically;
    z-index: 5;
    padding-top: 0.8em;
    background-color: var(--base-color-tone-10);
    box-shadow: 0 -1px var(--base-color-tone-20), inset 0 -1px var(--base-color-tone-20);
  }

  .statusbar {
    padding-top: 0.5em;
    padding-bottom: 0.5em;

    .status {
      font-size: 0.8em;
      color: var(--inverse-color-tone-10);
    }
  }

  .menubar,
  .statusbar {
    background-color: var(--base-color);
    -webkit-user-select: none;
    user-select: none;
  }
</style>
