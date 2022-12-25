<script lang="ts">
  import { faFolderOpen, faTrashAlt } from "@fortawesome/free-solid-svg-icons";
  import { JSONRPCError } from "@open-rpc/client-js";
  import { fade } from "svelte/transition";
  import type { Config, ValidationError } from "../api";
  import { Flavour } from "../api";
  import { activeProfile, api, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";

  export let editing: "new" | "existing" | false;

  const createNew = editing === "new";

  let profile: string;
  let addonDir: string;
  let gameFlavour: Flavour;

  let errors = new Map<string, string>();

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
    const { selection } = await $api.selectFolder(addonDir ?? null);
    if (selection !== null) {
      addonDir = selection;
    }
  };

  const saveConfig = async () => {
    if ((createNew && $profiles.has(profile)) || (!profile && $profiles.has("__default__"))) {
      errors.set(
        "profile",
        profile ? "a profile with that name already exists" : "a default profile already exists"
      );
      errors = errors;
      return;
    }

    let result: Config;
    try {
      result = await $api.writeProfile(profile, addonDir, gameFlavour, createNew);
    } catch (error) {
      if (error instanceof JSONRPCError) {
        errors = new Map(
          (error.data as ValidationError[]).map(({ loc: [loc], msg }) => [loc, msg])
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
    {#if errors.has("profile")}
      <div class="row error-text">{errors.get("profile")}</div>
    {/if}
    {#if createNew}
      <input
        aria-label="profile"
        class="row form-control"
        class:error={errors.has("profile")}
        type="text"
        placeholder="profile"
        bind:value={profile}
      />
    {/if}
    {#if errors.has("addon_dir")}
      <div class="row error-text">{errors.get("addon_dir")}</div>
    {/if}
    <div class="row input-array">
      <input
        aria-label="add-on folder"
        class="form-control"
        class:error={errors.has("addon_dir")}
        type="text"
        disabled
        placeholder="add-on folder"
        value={addonDir || ""}
      />
      <button
        aria-label="select folder"
        class="form-control"
        type="button"
        on:click|preventDefault={() => selectFolder()}
      >
        <Icon icon={faFolderOpen} />
      </button>
    </div>
    {#if !createNew}
      {#if errors.has("game_flavour")}
        <div class="row error-text">{errors.get("game_flavour")}</div>
      {/if}
      <select
        aria-label="game flavour"
        class="row form-control"
        class:error={errors.has("game_flavour")}
        bind:value={gameFlavour}
      >
        {#each Object.values(Flavour) as flavour}
          <option value={flavour}>{flavour}</option>
        {/each}
      </select>
    {/if}
    <div class="row input-array">
      <button class="form-control" type="submit">save</button>
      {#if !createNew}
        <button
          class="form-control"
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
