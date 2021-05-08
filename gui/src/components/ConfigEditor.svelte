<script lang="ts">
  import type { Api, Config, PydanticValidationError } from "../api";
  import { faFolderOpen, faTimesCircle } from "@fortawesome/free-solid-svg-icons";
  import { JSONRPCError } from "@open-rpc/client-js";
  import { fade } from "svelte/transition";
  import { Flavour } from "../api";
  import { ipcRenderer } from "../ipc";
  import { activeProfile, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let api: Api, editing: "new" | "existing" | false;

  const createNew = editing === "new";

  let configParams = (createNew
    ? { game_flavour: "retail" }
    : $profiles.get($activeProfile as string)) as Config;
  let errors: { [key: string]: string } = {};

  const selectFolder = async () => {
    const [cancelled, [path]] = await ipcRenderer.invoke("select-folder", configParams.addon_dir);
    if (!cancelled) {
      configParams.addon_dir = path;
    }
  };

  const saveConfig = async () => {
    if (
      (createNew && $profiles.has(configParams.profile)) ||
      (!configParams.profile && $profiles.has("__default__"))
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
      result = await api.writeProfile(configParams, createNew);
    } catch (error) {
      if (error instanceof JSONRPCError) {
        errors = Object.fromEntries(
          (error.data as PydanticValidationError[]).map(({ loc, msg }) => [loc, msg])
        );
        return;
      } else {
        throw error;
      }
    }

    $profiles = $profiles.set(result.profile, result);
    if (createNew) {
      $activeProfile = result.profile;
    }
    editing = false;
  };

  const deleteConfig = async () => {
    if (
      confirm(`Do you really want to delete this profile?

Deleting a profile does not delete your add-ons; it simply \
dissociates the add-on folder from instawow.  However, you \
will have to reconcile your add-ons again if you create \
a new profile for this folder and your rollback history \
will be lost.`)
    ) {
      await api.deleteProfile(configParams.profile);
      $profiles.delete(configParams.profile);
      $profiles = $profiles; // Trigger update in Svelte
      $activeProfile = $profiles.keys().next().value;
      editing = false;
    }
  };

  const dismissOnEsc = (e: KeyboardEvent) => e.key === "Escape" && (editing = false);
</script>

<svelte:window on:keydown={dismissOnEsc} />

<dialog
  open
  class="modal"
  style="--arrowhead-offset: {createNew ? 'calc(1rem - 8px)' : 'calc(3rem - 4px)'}"
  transition:fade={{ duration: 200 }}
>
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
        bind:value={configParams.profile}
      />
    {/if}
    {#if errors.addon_dir}
      <div class="row error-text">{errors.addon_dir}</div>
    {/if}
    <div class="row input-array">
      <input
        aria-label="add-on folder"
        class:error={errors.addon_dir}
        type="text"
        disabled
        placeholder="add-on folder"
        value={configParams.addon_dir || ""}
      />
      <button
        aria-label="select folder"
        type="button"
        on:click|preventDefault={() => selectFolder()}
      >
        <Icon icon={faFolderOpen} />
      </button>
    </div>
    {#if !createNew}
      {#if errors.game_flavour}
        <div class="row error-text">{errors.game_flavour}</div>
      {/if}
      <select
        aria-label="game flavour"
        class="row"
        class:error={errors.game_flavour}
        bind:value={configParams.game_flavour}
      >
        {#each Object.values(Flavour) as flavour}
          <option value={flavour}>{flavour}</option>
        {/each}
      </select>
    {/if}
    <div class="row input-array">
      <button type="submit">save</button>
      {#if !createNew}
        <button
          aria-label="delete profile"
          title="delete profile"
          type="button"
          on:click|preventDefault={() => deleteConfig()}
        >
          <Icon icon={faTimesCircle} />
        </button>
      {/if}
    </div>
  </form>
</dialog>

<style lang="scss">
  @import "scss/modal";

  .modal {
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
      border-bottom-color: var(--base-color-alpha-65);
      border-width: 8px;
      pointer-events: none;
    }
  }
</style>
