<script lang="ts">
  import { getContext, onDestroy } from "svelte";
  import { API_KEY, type Api } from "../stores/api.svelte";

  const api = getContext<Api>(API_KEY);

  let githubAuthFlowShouldStart = $state(false);
  let newCfcoreAccessToken = $state<string | null>(null);

  const updateCfCoreAccessToken = async () => {
    await api.updateGlobalConfig({ cfcore: newCfcoreAccessToken });
  };

  const queryGithubAuthFlowStatus = async () => {
    const { status } = await api.queryGithubAuthFlowStatus();
    githubAuthFlowShouldStart = false;
    return status;
  };

  onDestroy(() => {
    api.cancelGithubAuthFlow();
  });
</script>

<div class="title-bar">config</div>
<form class="content" onsubmit={(e) => e.preventDefault()}>
  {#await api.readGlobalConfig()}
    <div class="row">Loading...</div>
  {:then { access_tokens }}
    <div class="section-header">access tokens</div>
    <div class="row form-grid">
      <div class="label-like">GitHub:</div>
      <div class="value-rows">
        <button
          class="form-control"
          disabled={githubAuthFlowShouldStart}
          onclick={() => (githubAuthFlowShouldStart = true)}
        >
          {access_tokens.github === null ? "generate" : "regenerate"}
        </button>
        <div class="description">
          {#if githubAuthFlowShouldStart}
            {#await api.initiateGithubAuthFlow()}
              Initiating authorisation flow...
            {:then { verification_uri, user_code }}
              {#await queryGithubAuthFlowStatus()}
                Navigate to
                <button
                  role="link"
                  onclick={(e) => {
                    e.preventDefault();
                    api.openUrl(verification_uri);
                  }}
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
            Generating an access token for GitHub is recommended to avoid being rate limited. You
            may only perform 60 requests an hour without an access token.
          {/if}
        </div>
      </div>
      <label for="__cfcore-input-box">CurseForge:</label>
      <div class="value-rows">
        <input
          id="__cfcore-input-box"
          class="form-control"
          type="password"
          value={access_tokens.cfcore}
          oninput={(e) => (newCfcoreAccessToken = e.currentTarget.value || null)}
        />
        <button
          class="form-control primary"
          disabled={newCfcoreAccessToken === undefined}
          onclick={() => updateCfCoreAccessToken()}>update</button
        >
        <div class="description">
          An API key is required to use CurseForge. Log in to
          <button
            role="link"
            onclick={(e) => {
              e.preventDefault();
              api.openUrl("https://console.curseforge.com/");
            }}
          >
            CurseForge for Studios
          </button> to generate a key.
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
