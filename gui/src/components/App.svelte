<script lang="ts">
  import type { Version } from "../api";
  import { RequestManager, Client, WebSocketTransport } from "@open-rpc/client-js";
  import { ipcRenderer } from "electron";
  import lodash from "lodash";
  import { Lock } from "semaphore-async-await";
  import { Api } from "../api";
  import { activeProfile, profiles } from "../store";
  import ProfileView from "./ProfileView.svelte";
  import ProfileSwitcher from "./ProfileSwitcher.svelte";

  let _transport: WebSocketTransport;
  let _client: Client;
  let api: Api;
  let instawowVersions: Version;

  const _clientInitialisationLock = new Lock();

  const _connectToServer = async (): Promise<[WebSocketTransport, Client]> => {
    const address = await ipcRenderer.invoke("get-server-address");
    const endpoint = new URL("/v0", address).toString();
    const transport = new WebSocketTransport(endpoint);
    const requestManager = new RequestManager([transport]);
    const client = new Client(requestManager);
    return [transport, client];
  };

  const getClient = async () => {
    await _clientInitialisationLock.acquire();
    try {
      if (
        typeof _client === "undefined" ||
        [WebSocket.CLOSING, WebSocket.CLOSED].includes(_transport.connection.readyState)
      ) {
        [_transport, _client] = await _connectToServer();
      }
      return _client;
    } finally {
      _clientInitialisationLock.release();
    }
  };

  const setup = async () => {
    api = new Api(getClient);
    instawowVersions = await api.getVersion();
    const profileNames = await api.enumerateProfiles();
    const profileConfigs = await Promise.all(profileNames.map((p) => api.readProfile(p)));
    $profiles = lodash.fromPairs(lodash.zip(profileNames, profileConfigs));
    $activeProfile = profileNames[0];
  };
</script>

<style lang="scss">
  @import "vars";

  :global(:root) {
    --base-color: #{$base-color-light};
    --base-color-65: #{rgba($base-color-light, 0.65)};
    --inverse-color: #{$inverse-color-light};
    --inverse-color-05: #{rgba($inverse-color-light, 0.05)};
    --inverse-color-10: #{rgba($inverse-color-light, 0.1)};
    --inverse-color-20: #{rgba($inverse-color-light, 0.2)};
    --inverse-color-tone-10: #{lighten($inverse-color-light, 10%)};
    --inverse-color-tone-20: #{lighten($inverse-color-light, 20%)};
    --dropdown-arrow: #{generate-dropdown-arrow($inverse-color-light)};
  }

  @media (prefers-color-scheme: dark) {
    :global(:root) {
      --base-color: #{$base-color-dark};
      --base-color-65: #{rgba($base-color-dark, 0.65)};
      --inverse-color: #{$inverse-color-dark};
      --inverse-color-05: #{rgba($inverse-color-dark, 0.05)};
      --inverse-color-10: #{rgba($inverse-color-dark, 0.15)};
      --inverse-color-20: #{rgba($inverse-color-dark, 0.25)};
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
  }

  .section {
    padding: 0 0.8em;

    &__menubar {
      display: flex;
      align-items: center;
      min-height: 55px;
      padding-left: 95px;

      .instawow-version {
        flex-grow: 1;
        text-align: right;
        font-family: $mono-font-stack;
        font-size: 0.7em;
      }
    }

    &__main {
      @include stretch-vertically;
      padding-top: 0.8em;
      padding-bottom: 0.8em;
      background-color: var(--base-color);
      box-shadow: 0 1px 0px 0 var(--inverse-color-10), 0 -1px 0px 0 var(--inverse-color-10);
    }

    &__statusbar {
      padding-top: 0.5em;
      padding-bottom: 0.5em;

      .status {
        font-size: 0.8em;
      }
    }

    &__menubar,
    &__statusbar {
      -webkit-app-region: drag; /* */
      -webkit-user-select: none;
    }
  }
</style>

{#await setup()}
  <main>
    <header class="section section__menubar" />
    <section class="section section__main" />
    <footer class="section section__statusbar">
      <div class="status">Loading…</div>
    </footer>
  </main>
{:then}
  <main>
    <header class="section section__menubar">
      <ProfileSwitcher {api} />
      <div class="instawow-version">
        <b>instawow</b>
        <br />
        {instawowVersions.installed_version}
        {instawowVersions.new_version ? `< ${instawowVersions.new_version}` : ''}
      </div>
    </header>
    <section class="section section__main">
      {#each Object.keys($profiles) as profile}
        <ProfileView
          {profile}
          api={api.withProfile(profile)}
          isActive={profile === $activeProfile} />
      {/each}
    </section>
    <footer class="section section__statusbar">
      <div class="status">&nbsp;</div>
    </footer>
  </main>
{/await}
