<script lang="ts">
  import type { Config } from "../api";
  import { faFolderOpen } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";
  import { activeProfile, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let createNew: boolean;

  let configParams = { ...(createNew ? {} : $profiles[$activeProfile]) } as Config;

  const dispatch = createEventDispatcher();

  const selectFolder = async () => {
    const [cancelled, [path]] = await ipcRenderer.invoke("select-folder");
    if (!cancelled) {
      configParams.addon_dir = path;
    }
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

    &.submit {
      background-color: $action-button-bg-color;
      color: $action-button-text-color;

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

  .input-row + .input-row {
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
</style>

<div
  class="config-editor-wrapper"
  style="--arrowhead-offset: {createNew ? '.5rem' : '2.5rem'}"
  transition:fade={{ duration: 200 }}>
  <form on:keydown on:submit|preventDefault>
    {#if createNew}
      <input
        class="input-row"
        type="text"
        placeholder="profile"
        name="profile"
        autofocus
        bind:value={configParams.profile} />
    {/if}
    <select class="input-row" name="game_flavour" bind:value={configParams.game_flavour}>
      <option value="retail">retail</option>
      <option value="classic">classic</option>
    </select>
    <div class="input-row select-folder-array">
      <input
        type="text"
        disabled
        placeholder="select folder"
        value={configParams.addon_dir || ''} />
      <button on:click|preventDefault={() => selectFolder()}>
        <Icon icon={faFolderOpen} />
      </button>
    </div>
    <button
      class="input-row submit"
      on:click|preventDefault={() => dispatch('requestSaveConfig', configParams)}>
      save
    </button>
  </form>
</div>
