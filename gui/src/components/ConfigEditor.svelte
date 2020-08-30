<script lang="ts">
  import type { Api, Config } from "../api";
  import { faFolderOpen } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import { fade } from "svelte/transition";
  import { activeProfile, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let api: Api, editing: "new" | "existing" | false;

  const createNew = editing === "new";

  let configParams = { ...(createNew ? {} : $profiles[$activeProfile]) } as Config;
  let errors: { [key: string]: string } = {};

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

  const dismissOnEsc = () => {
    const handler = (e) => e.key === "Escape" && (editing = false);
    document.body.addEventListener("keydown", handler);
    return {
      destroy: () => document.body.removeEventListener("keydown", handler),
    };
  };
</script>

<style lang="scss">
  @import "modal";

  .config-editor {
    @extend .modal;

    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 10;

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
</style>

<dialog
  open
  class="config-editor"
  style="--arrowhead-offset: {createNew ? 'calc(1rem - 8px)' : 'calc(3rem - 4px)'}"
  transition:fade={{ duration: 200 }}
  use:dismissOnEsc>
  <form class="content" on:submit|preventDefault={() => saveConfig()}>
    {#if errors.profile}
      <div class="row error-text">{errors.profile}</div>
    {/if}
    {#if createNew}
      <input
        class="row"
        class:error={errors.profile}
        type="text"
        label="profile"
        placeholder="profile"
        name="profile"
        bind:value={configParams.profile} />
    {/if}
    {#if errors.addon_dir}
      <div class="row error-text">{errors.addon_dir}</div>
    {/if}
    <div class="row select-folder-array">
      <input
        aria-label="add-on folder"
        class:error={errors.addon_dir}
        type="text"
        disabled
        placeholder="add-on folder"
        value={configParams.addon_dir || ''} />
      <button aria-label="select folder" on:click|preventDefault={() => selectFolder()}>
        <Icon icon={faFolderOpen} />
      </button>
    </div>
    {#if errors.game_flavour}
      <div class="row error-text">{errors.game_flavour}</div>
    {/if}
    <select
      aria-label="game flavour"
      class="row"
      class:error={errors.game_flavour}
      name="game_flavour"
      bind:value={configParams.game_flavour}>
      <option value="retail">retail</option>
      <option value="classic">classic</option>
    </select>
    <button class="row submit" type="submit">save</button>
  </form>
</dialog>
