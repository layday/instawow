<script lang="ts">
  import { fade } from "svelte/transition";
  import { api } from "../stores/api";
  import { activeProfile, profiles } from "../stores/profiles";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";
  import ProfileView from "./ProfileView.svelte";
  import type { Config } from "../api";
  import Alerts from "./Alerts.svelte";

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

  let statusMessage = $state(" ");

  let installedVersion = $state<string>();
  let newVersion = $state<string | null>();

  const performInitialSetup = async () => {
    ({ installed_version: installedVersion, new_version: newVersion } = await $api.getVersion());

    const profileNames = await $api.listProfiles();
    const profileResults = await Promise.allSettled(profileNames.map((p) => $api.readProfile(p)));

    $profiles = Object.fromEntries(
      profileResults
        .filter((r): r is PromiseFulfilledResult<Config> => r.status === "fulfilled")
        .map(({ value }) => [value.profile, value]),
    );
    [$activeProfile] = Object.keys($profiles);
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
      {#each Object.keys($profiles) as profile (profile)}
        <ProfileView bind:statusMessage {profile} isActive={profile === $activeProfile} />
      {/each}
    </main>
    <footer class="section statusbar">
      <div class="status" in:fade>{statusMessage}</div>
    </footer>
  {/await}
  <Alerts />
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
