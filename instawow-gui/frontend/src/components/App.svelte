<script lang="ts">
  import { getContext } from "svelte";
  import { fade } from "svelte/transition";
  import { type Config } from "../api";
  import { API_KEY, type Api } from "../stores/api.svelte";
  import {
    ACTIVE_PROFILE_KEY,
    PROFILES_KEY,
    type ActiveProfileRef,
    type ProfilesRef,
  } from "../stores/profiles.svelte";
  import Alerts from "./Alerts.svelte";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";
  import Profile from "./Profile.svelte";

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

  const profilesRef = getContext<ProfilesRef>(PROFILES_KEY);
  const activeProfileRef = getContext<ActiveProfileRef>(ACTIVE_PROFILE_KEY);
  const api = getContext<Api>(API_KEY);

  let statusMessage = $state(" ");

  let installedVersion = $state<string>();
  let newVersion = $state<string | null>();

  const performInitialSetup = async () => {
    ({ installed_version: installedVersion, new_version: newVersion } = await api.getVersion());

    const profiles = await api.listProfiles();
    profilesRef.value = profiles;
    [activeProfileRef.value] = Object.keys(profilesRef.value);
  };
</script>

<svelte:head>
  <style lang="scss">
    @use "scss/app";
  </style>
</svelte:head>

<div class="wrapper" style={pickRandomBorderColour()}>
  {#await performInitialSetup()}
    <header class="section menubar"></header>
    <main class="section main"></main>
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
      {#each Object.keys(profilesRef.value) as profile (profile)}
        <Profile bind:statusMessage {profile} isActive={profile === activeProfileRef.value} />
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
    background-color: var(--base-color-tone-a);
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
