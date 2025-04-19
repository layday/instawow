<script lang="ts">
  import { getContext } from "svelte";
  import { API_KEY, type Api } from "../stores/api.svelte";
  import type { GithubAuthFlowStatusReport, GithubCodesResponse, GlobalConfig } from "../api";
  import { makeDuplicativeState } from "../helpers/duplicative-state.svelte";

  const api = getContext<Api>(API_KEY);

  let accessTokens = makeDuplicativeState<GlobalConfig["access_tokens"]>({
    cfcore: null,
    github: null,
    wago_addons: null,
  });

  let githubAuthFlow = $state<
    | { step: "starting" }
    | ({ step: "started" } & GithubCodesResponse)
    | ({ step: "completed" } & GithubAuthFlowStatusReport)
  >();

  const loadAccessTokens = async () => {
    const { access_tokens } = await api.readGlobalConfig();
    accessTokens.reset(access_tokens);
  };

  const updateAccessTokens = async (...names: (keyof GlobalConfig["access_tokens"])[]) => {
    const { access_tokens } = await api.updateGlobalConfig({
      access_tokens: Object.fromEntries(names.map((n) => [n, accessTokens.current[n] || null])),
    });
    accessTokens.reset(access_tokens);
  };

  const startGithubAuthFlow = async () => {
    githubAuthFlow = { step: "starting" };

    const codes = await api.initiateGithubAuthFlow();
    githubAuthFlow = { step: "started", ...codes };

    const { status } = await api.queryGithubAuthFlowStatus();
    if (status === "success") {
      const { access_tokens } = await api.readGlobalConfig();
      accessTokens.reset(access_tokens);
    }
    githubAuthFlow = { step: "completed", status };
  };
</script>

<div class="title-bar">config</div>
<form class="content" onsubmit={(e) => e.preventDefault()}>
  {#await loadAccessTokens()}
    <div class="row">Loading...</div>
  {:then}
    <div class="section-header">access tokens</div>
    <div class="row form-grid">
      <div class="label-like">GitHub:</div>
      <div>
        <button
          class="form-control"
          disabled={githubAuthFlow && githubAuthFlow.step !== "completed"}
          onclick={() => startGithubAuthFlow()}
        >
          {accessTokens.initial.github === null ? "generate" : "regenerate"}
        </button>
        <p class="description">
          {#if githubAuthFlow?.step === "starting"}
            Initiating authorisation flow...
          {:else if githubAuthFlow?.step === "started"}
            {@const { verification_uri, user_code } = githubAuthFlow}
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
            and insert the following code to authenticate with instawow: "<code>{user_code}</code
            >".
          {:else if githubAuthFlow?.step === "completed"}
            {#if githubAuthFlow.status === "success"}
              Authenticated.
            {:else if githubAuthFlow.status === "failure"}
              Authentication failed.
            {/if}
          {:else}
            Generate an access token for GitHub to avoid being rate limited. You are only allowed
            to perform 60 requests an hour without one.
          {/if}
        </p>
      </div>

      <label for="__cfcore-input-box">CurseForge:</label>
      <div>
        <div class="input-array">
          <input
            id="__cfcore-input-box"
            class="form-control"
            type="password"
            bind:value={accessTokens.current.cfcore}
          />
          <button
            class="form-control primary"
            disabled={accessTokens.initial.cfcore === accessTokens.current.cfcore}
            onclick={() => updateAccessTokens("cfcore")}>update</button
          >
        </div>
        <p class="description">
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
        </p>
      </div>

      <label for="__wago-input-box">Wago Addons:</label>
      <div>
        <div class="input-array">
          <input
            id="__wago-input-box"
            class="form-control"
            type="password"
            bind:value={accessTokens.current.wago_addons}
          />

          <button
            class="form-control primary"
            disabled={accessTokens.initial.wago_addons === accessTokens.current.wago_addons}
            onclick={() => updateAccessTokens("wago_addons")}>update</button
          >
        </div>
        <p class="description">
          An access token is required to use Wago Addons. Wago issues tokens to
          <button
            role="link"
            onclick={(e) => {
              e.preventDefault();

              api.openUrl("https://addons.wago.io/patreon");
            }}
          >
            Patreon
          </button> subscribers above a certain tier.
        </p>
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

  .description {
    margin: 0.25rem;
    font-size: 0.875em;
    color: var(--inverse-color-tone-b);
  }
</style>
