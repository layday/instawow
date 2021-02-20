<script lang="ts">
  import type { Api, Version } from "../api";
  import { fade } from "svelte/transition";
  import { activeProfile, profiles } from "../store";
  import ProfileView from "./ProfileView.svelte";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";

  export let api: Api;

  let instawowVersions: Version;
  let installedAddonCount = 0;

  const doInitialSetup = async () => {
    const profileNames = await api.listProfiles();
    const profileConfigs = await Promise.all(profileNames.map((p) => api.readProfile(p)));
    $profiles = new Map(profileNames.map((n, i) => [n, profileConfigs[i]]));
    $activeProfile = profileNames[0];
    instawowVersions = await api.getVersion();
  };
</script>

{#await doInitialSetup()}
  <main>
    <header class="section section__menubar" />
    <section class="section section__main" />
    <footer class="section section__statusbar">
      <div class="status">loading…</div>
    </footer>
  </main>
{:then}
  <main>
    <header class="section section__menubar">
      <ProfileSwitcher {api} />
      <div class="instawow-version">
        <b>instawow</b>
        <br />
        <span>
          {instawowVersions.installed_version}
          {instawowVersions.new_version ? `< ${instawowVersions.new_version}` : ""}
        </span>
      </div>
    </header>
    <section class="section section__main">
      {#each [...$profiles.keys()] as profile (profile)}
        <ProfileView
          bind:installedAddonCount
          {profile}
          api={api.withProfile(profile)}
          isActive={profile === $activeProfile}
        />
      {/each}
    </section>
    <footer class="section section__statusbar">
      <div class="status" in:fade>installed add-ons: {installedAddonCount}</div>
    </footer>
  </main>
{/await}

<style lang="scss">
  @import "scss/vars";

  :global(:root) {
    --base-color: #{$base-color-light};
    --base-color-alpha-65: #{rgba($base-color-light, 0.65)};
    --inverse-color: #{$inverse-color-light};
    --inverse-color-alpha-05: #{rgba($inverse-color-light, 0.05)};
    --inverse-color-alpha-10: #{rgba($inverse-color-light, 0.1)};
    --inverse-color-alpha-20: #{rgba($inverse-color-light, 0.2)};
    --inverse-color-tone-10: #{lighten($inverse-color-light, 10%)};
    --inverse-color-tone-20: #{lighten($inverse-color-light, 20%)};
    --dropdown-arrow: #{generate-dropdown-arrow($inverse-color-light)};
  }

  @media (prefers-color-scheme: dark) {
    :global(:root) {
      --base-color: #{$base-color-dark};
      --base-color-alpha-65: #{rgba($base-color-dark, 0.65)};
      --inverse-color: #{$inverse-color-dark};
      --inverse-color-alpha-05: #{rgba($inverse-color-dark, 0.05)};
      --inverse-color-alpha-10: #{rgba($inverse-color-dark, 0.15)};
      --inverse-color-alpha-20: #{rgba($inverse-color-dark, 0.25)};
      --inverse-color-tone-10: #{darken($inverse-color-dark, 05%)};
      --inverse-color-tone-20: #{darken($inverse-color-dark, 10%)};
      --dropdown-arrow: #{generate-dropdown-arrow($inverse-color-dark)};
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
    font-family: system-ui;
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
  }

  main {
    display: flex;
    flex-direction: column;
    height: 100vh;

    .section__menubar,
    .section__statusbar {
      background-color: var(--base-color);
    }
  }

  .section {
    padding: 0 0.8em;

    &__menubar {
      display: flex;
      align-items: center;
      min-height: 55px;

      .instawow-version {
        flex-grow: 1;
        text-align: right;
        font-family: $mono-font-stack;
        font-size: 0.7em;

        span {
          color: var(--inverse-color-tone-10);
        }
      }
    }

    &__main {
      @include stretch-vertically;
      z-index: 5;
      padding-top: 0.8em;
      background-color: var(--base-color);
      box-shadow: 0 -1px 0px 0 var(--inverse-color-alpha-10);
    }

    &__statusbar {
      padding-top: 0.5em;
      padding-bottom: 0.5em;

      .status {
        font-size: 0.8em;
        color: var(--inverse-color-tone-10);
      }
    }

    &__menubar,
    &__statusbar {
      -webkit-user-select: none;
    }
  }
</style>
