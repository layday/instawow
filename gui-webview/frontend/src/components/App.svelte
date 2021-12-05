<script lang="ts">
  import { fade } from "svelte/transition";
  import type { Config } from "../api";
  import { activeProfile, api, profiles } from "../store";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";
  import ProfileView from "./ProfileView.svelte";

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
