<script lang="ts">
  import { onDestroy } from "svelte";
  import { api } from "../stores/api";

  let githubAuthFlowShouldStart = false;
  let newCfcoreAccessToken: string | null;
  let newWagoAccessToken: string | null;

  const updateCfCoreAccessToken = async () => {
    await $api.updateGlobalConfig({ cfcore: newCfcoreAccessToken });
  };

  const updateWagoAccessToken = async () => {
    await $api.updateGlobalConfig({ wago_addons: newWagoAccessToken });
  };

  const queryGithubAuthFlowStatus = async () => {
    const { status } = await $api.queryGithubAuthFlowStatus();
    githubAuthFlowShouldStart = false;
    return status;
  };

  onDestroy(() => {
    $api.cancelGithubAuthFlow();
  });
</script>

<div class="title-bar">config</div>
<form class="content" on:submit|preventDefault>
  {#await $api.readGlobalConfig()}
    <div class="row">Loading...</div>
  {:then { access_tokens }}
    <div class="section-header">access tokens</div>
    <div class="row form-grid">
      <div class="label-like">GitHub:</div>
      <div class="value-rows">
        <button
          class="form-control"
          disabled={githubAuthFlowShouldStart}
          on:click={() => (githubAuthFlowShouldStart = true)}
        >
          {access_tokens.github === null ? "generate" : "regenerate"}
        </button>
        <div class="description">
          {#if githubAuthFlowShouldStart}
            {#await $api.initiateGithubAuthFlow()}
              Initiating authorisation flow...
            {:then { verification_uri, user_code }}
              {#await queryGithubAuthFlowStatus()}
                Navigate to
                <button
                  role="link"
                  on:click|preventDefault|stopPropagation={() => $api.openUrl(verification_uri)}
                >
                  {verification_uri}
                </button>
                and insert the following code to authenticate with instawow: "<code
                  >{user_code}</code
                >".
              {:then status}
                {#if status === "success"}
                  Authenticated.
                {:else if status === "failure"}
                  Authentication failed.
                {/if}
              {/await}
            {/await}
          {:else}
            Generate a GitHub access token to increase your hourly limit from 60 to 5,000 requests.
          {/if}
        </div>
      </div>
      <label for="__cfcore-input-box">CFCore:</label>
      <div class="value-rows">
        <input
          id="__cfcore-input-box"
          class="form-control"
          type="password"
          value={access_tokens.cfcore}
          on:input={(e) => (newCfcoreAccessToken = e.currentTarget.value || null)}
        />
        <button
          class="form-control primary"
          disabled={newCfcoreAccessToken === undefined}
          on:click={() => updateCfCoreAccessToken()}>update</button
        >
        <div class="description">
          A CFCore access token is required to use CurseForge. Log in to
          <button
            role="link"
            on:click|preventDefault|stopPropagation={() =>
              $api.openUrl("https://console.curseforge.com/")}
          >
            CFCore
          </button> to generate an access token.
        </div>
      </div>
      <label for="__wago-input-box">Wago:</label>
      <div class="value-rows">
        <input
          id="__wago-input-box"
          class="form-control"
          type="password"
          value={access_tokens.wago_addons}
          on:input={(e) => (newWagoAccessToken = e.currentTarget.value || null)}
        />
        <button
          class="form-control primary"
          disabled={newWagoAccessToken === undefined}
          on:click={() => updateWagoAccessToken()}>update</button
        >
        <div class="description">
          An access token is required to use Wago Addons. Wago issues tokens to some
          <button
            role="link"
            on:click|preventDefault|stopPropagation={() =>
              $api.openUrl("https://addons.wago.io/patreon")}
          >
            Patreon
          </button> subscribers.
        </div>
      </div>
    </div>
  {/await}
</form>

<style lang="scss">
  @use "scss/vars";

  .content {
    overflow: auto;
  }

  .form-grid {
    display: grid;
    grid-template-columns: 1fr 2fr;
    column-gap: 0.5rem;
    row-gap: 0.75rem;

    label,
    .label-like {
      line-height: vars.$modal-form-el-line-height;
      color: var(--inverse-color-tone-a);
      text-align: right;
    }
  }

  .section-header {
    margin-bottom: 1rem;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid var(--inverse-color-tone-b);
    font-weight: 500;
    text-align: center;
  }

  .value-rows {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .description {
    font-size: 0.875em;
    color: var(--inverse-color-tone-b);
  }
</style>
