<script lang="ts">
  import type { Api, Config } from "../api";
  import { faFolderOpen } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import { fade } from "svelte/transition";
  import { activeProfile, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let api: Api, editing: "new" | "existing" | boolean;

  const createNew = editing === "new";

  let configParams = { ...(createNew ? {} : $profiles[$activeProfile]) } as Config;
  let errors: { [key: string]: any } = {};

  const selectFolder = async () => {
    const [cancelled, [path]] = await ipcRenderer.invoke("select-folder", configParams.addon_dir);
    if (!cancelled) {
      configParams.addon_dir = path;
    }
  };

  const saveConfig = async () => {
    if (
      (createNew && configParams.profile in $profiles) ||
      (!configParams.profile && "__default__" in $profiles)
    ) {
      if (!configParams.profile) {
        errors = { profile: "a default profile already exists" };
      } else {
        errors = { profile: "a profile with that name already exists" };
      }
      return;
    }

    let result: Config;
    try {
      result = await api.writeProfile(configParams);
    } catch (error) {
      // `error instanceof JSONRPCError` isn't working because of some transpilation fuckery:
      // https://github.com/open-rpc/client-js/issues/209
      if (error?.data) {
        errors = Object.fromEntries(error.data.map(({ loc, msg }) => [loc, msg]));
        return;
      } else {
        throw error;
      }
    }

    $profiles[result.profile] = result;
    if (createNew) {
      $activeProfile = result.profile;
    }
    editing = false;
  };
</script>

<style lang="scss">
  @import "vars";

  $line-height: 1.8em;
  $middle-border-radius: $line-height / 6;
  $edge-border-radius: $line-height / 4;

  .config-editor-wrapper {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 10;
    padding: 1.25rem;
    border-radius: 0.25rem;
    box-shadow: 0 10px 20px var(--inverse-color-05);
    background-color: var(--base-color-65);
    backdrop-filter: blur(5px);

    &::before {
      content: "";
      position: absolute;
      bottom: 100%;
      right: var(--arrowhead-offset);
      border: solid transparent;
      border-bottom-color: var(--base-color-65);
      border-width: 8px;
      pointer-events: none;
    }
  }

  button,
  input,
  select {
    display: block;
    width: 100%;
    line-height: $line-height;
    padding: 0 0.75em;
    border: 0;
    border-radius: $edge-border-radius;
    background-color: var(--inverse-color-10);
    transition: background-color 0.2s;

    &:disabled {
      opacity: 0.5;
    }

    &:focus {
      background-color: var(--inverse-color-20);
    }

    &.error {
      background-color: salmon;
    }

    &.submit {
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
      font-weight: 500;

      &:focus {
        background-color: $action-button-focus-bg-color;
      }
    }

    :global(.icon) {
      height: 16px;
      width: 16px;
      fill: var(--inverse-color);
      vertical-align: text-bottom;
    }
  }

  select {
    background-image: var(--dropdown-arrow);
    background-size: 10px;
    background-repeat: no-repeat;
    background-position: top 9px right 7px;
    min-width: 200px;
    -webkit-appearance: none;
  }

  .row + .row {
    margin-top: 0.5rem;
  }

  .select-folder-array {
    display: flex;

    button,
    input {
      border-radius: $middle-border-radius;

      + button,
      + input {
        margin-left: 4px;
      }
    }

    button {
      width: auto;
    }

    input {
      flex-grow: 1;
    }

    :first-child {
      border-top-left-radius: $edge-border-radius;
      border-bottom-left-radius: $edge-border-radius;
    }

    :last-child {
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
    }
  }

  .error-text {
    line-height: 1;
    color: salmon;
    font-size: 0.9em;

    :not(:first-child) {
      padding-top: 0.25rem;
    }
  }
</style>

<div
  class="config-editor-wrapper"
  style="--arrowhead-offset: {createNew ? 'calc(1rem - 8px)' : 'calc(3rem - 4px)'}"
  transition:fade={{ duration: 200 }}>
  <form on:keydown={(e) => e.key === 'Escape' && (editing = false)} on:submit|preventDefault>
    {#if errors.profile}
      <div class="row error-text">{errors.profile}</div>
    {/if}
    {#if createNew}
      <input
        class="row"
        class:error={errors.profile}
        type="text"
        placeholder="profile"
        name="profile"
        autofocus
        bind:value={configParams.profile} />
    {/if}
    {#if errors.game_flavour}
      <div class="row error-text">{errors.game_flavour}</div>
    {/if}
    <select
      class="row"
      class:error={errors.game_flavour}
      name="game_flavour"
      bind:value={configParams.game_flavour}>
      <option value="retail">retail</option>
      <option value="classic">classic</option>
    </select>
    {#if errors.addon_dir}
      <div class="row error-text">{errors.addon_dir}</div>
    {/if}
    <div class="row select-folder-array">
      <input
        class:error={errors.addon_dir}
        type="text"
        disabled
        placeholder="select folder"
        value={configParams.addon_dir || ''} />
      <button on:click|preventDefault={() => selectFolder()}>
        <Icon icon={faFolderOpen} />
      </button>
    </div>
    <button class="row submit" on:click|preventDefault={() => saveConfig()}>save</button>
  </form>
</div>
