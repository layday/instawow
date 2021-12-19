<script lang="ts">
  import { faFolderOpen, faTrashAlt } from "@fortawesome/free-solid-svg-icons";
  import { JSONRPCError } from "@open-rpc/client-js";
  import lodash from "lodash";
  import { fade } from "svelte/transition";
  import type { Config, PydanticValidationError } from "../api";
  import { Flavour } from "../api";
  import { activeProfile, api, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let editing: "new" | "existing" | false;

  const createNew = editing === "new";

  let profile: string;
  let addonDir: string;
  let gameFlavour: Flavour;

  let errors: { [key: string]: string } = {};

  if (createNew) {
    gameFlavour = Flavour.retail;
  } else {
    ({
      profile,
      addon_dir: addonDir,
      game_flavour: gameFlavour,
    } = $profiles.get($activeProfile!)!);
  }

  const selectFolder = async () => {
    const { selection } = await $api.selectFolder(addonDir);
    if (selection !== null) {
      addonDir = selection;
    }
  };

  const saveConfig = async () => {
    if ((createNew && $profiles.has(profile)) || (!profile && $profiles.has("__default__"))) {
      if (!profile) {
        errors = { profile: "a default profile already exists" };
      } else {
        errors = { profile: "a profile with that name already exists" };
      }
      return;
    }

    let result: Config;
    try {
      result = await $api.writeProfile(profile, addonDir, gameFlavour, createNew);
    } catch (error) {
      if (error instanceof JSONRPCError) {
        errors = lodash.fromPairs(
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
    const { ok } = await $api.confirm(
      "Delete profile",
      `Do you really want to delete this profile?

Deleting a profile does not delete your add-ons; it simply \
dissociates the add-on folder from instawow.  However, you \
will have to reconcile your add-ons again if you create \
a new profile for this folder and your rollback history \
will be lost.`
    );
    if (ok) {
      await $api.deleteProfile(profile);
      $profiles.delete(profile);
      $profiles = $profiles; // Trigger update in Svelte
      $activeProfile = $profiles.keys().next().value;
      editing = false;
    }
  };

  const dismissOnEsc = (e: KeyboardEvent) => e.key === "Escape" && (editing = false);
</script>

<svelte:window on:keydown={dismissOnEsc} />

<dialog open class="modal" transition:fade={{ duration: 200 }}>
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
        bind:value={profile}
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
        value={addonDir || ""}
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
        bind:value={gameFlavour}
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
          <Icon icon={faTrashAlt} />
        </button>
      {/if}
    </div>
  </form>
</dialog>

<style lang="scss">
  .modal {
    position: absolute;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    z-index: 10;
  }
</style>
