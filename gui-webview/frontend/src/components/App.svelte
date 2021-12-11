<script lang="ts">
  import { fade } from "svelte/transition";
  import type { Config } from "../api";
  import { activeProfile, api, profiles } from "../store";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";
  import ProfileView from "./ProfileView.svelte";

  // Nicked from Peacock
  const colourPalette = [
    "#dd0531",
    "#007fff",
    "#f9e64f",
    "#1857a4",
    "#215732",
    "#61dafb",
    "#832561",
    "#ff3d00",
    "#42b883",
  ];

  const pickRandomBorderColour = () => {
    const index = Math.max(0, Math.round(Math.random() * colourPalette.length) - 1);
    return `
      --random-border-color: ${colourPalette[index]};
    `;
  };

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

<svelte:head>
  <style lang="scss">
    @use "scss/app";
  </style>
</svelte:head>

<div class="wrapper" style={pickRandomBorderColour()}>
  {#await performInitialSetup()}
    <header class="section menubar" />
    <main class="section main" />
    <footer class="section statusbar">
      <div class="status">loading…</div>
    </footer>
  {:then}
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
  {/await}
</div>

<style lang="scss">
  @use "scss/vars";

  .wrapper {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }

  .menubar {
    display: flex;
    align-items: center;
    min-height: 55px;
    background-color: var(--base-color);

    .instawow-version {
      flex-grow: 1;
      text-align: right;
      font-family: vars.$mono-font-stack;
      font-size: 0.7em;

      span {
        color: var(--inverse-color-tone-a);
      }
    }
  }

  .main {
    @extend %stretch-vertically;
    padding: 0;
    z-index: 5;
    background-color: var(--base-color-tone-a);
    border-top: 4px solid var(--random-border-color);
  }

  .menubar,
  .statusbar {
    padding: 0 0.8em;
    -webkit-user-select: none;
    user-select: none;
  }

  .statusbar {
    padding-top: 0.5em;
    padding-bottom: 0.5em;
    background-color: var(--base-color);
    box-shadow: inset 0 1px var(--base-color-tone-b);

    .status {
      font-size: 0.8em;
      color: var(--inverse-color-tone-a);
    }
  }
</style>
