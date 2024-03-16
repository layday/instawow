<script lang="ts">
  import { faFolderOpen, faTrashAlt } from "@fortawesome/free-solid-svg-icons";
  import { JSONRPCError } from "@open-rpc/client-js";
  import ld from "lodash-es";
  import { getContext } from "svelte";
  import { fade } from "svelte/transition";
  import type { Config, ValidationError } from "../api";
  import { Flavour } from "../api";
  import { API_KEY, type Api } from "../stores/api.svelte";
  import {
    ACTIVE_PROFILE_KEY,
    PROFILES_KEY,
    type ActiveProfileRef,
    type ProfilesRef,
  } from "../stores/profiles.svelte";
  import Icon from "./SvgIcon.svelte";

  const profilesRef = getContext<ProfilesRef>(PROFILES_KEY);
  const activeProfileRef = getContext<ActiveProfileRef>(ACTIVE_PROFILE_KEY);
  const api = getContext<Api>(API_KEY);

  let {
    editing,
  }: {
    editing: "new" | "existing" | false;
  } = $props();

  let createNew = $derived(editing === "new");

  let profileConfig = $state(
    {} as {
      profile: string;
      addonDir: string;
      gameFlavour: Flavour;
    },
  );

  let errors = $state(new Map<string, string>());

  $effect.pre(() => {
    if (createNew) {
      profileConfig.gameFlavour = Flavour.Retail;
    } else {
      ({
        profile: profileConfig.profile,
        addon_dir: profileConfig.addonDir,
        game_flavour: profileConfig.gameFlavour,
      } = profilesRef.value[activeProfileRef.value as string]);
    }
  });

  const selectFolder = async () => {
    const { selection } = await api.selectFolder(profileConfig.addonDir ?? null);
    if (selection !== null) {
      profileConfig.addonDir = selection;
    }
  };

  const saveConfig = async () => {
    if (
      (createNew && profileConfig.profile in profilesRef.value) ||
      (!profileConfig.profile && "__default__" in profilesRef.value)
    ) {
      errors.set(
        "profile",
        profileConfig.profile
          ? "a profile with that name already exists"
          : "a default profile already exists",
      );
      errors = errors;
      return;
    }

    let result: Config;
    try {
      result = await api.writeProfile(
        profileConfig.profile,
        profileConfig.addonDir,
        profileConfig.gameFlavour,
        createNew,
      );
    } catch (error) {
      if (error instanceof JSONRPCError) {
        console.log(error);
        errors = new Map(
          (error.data as ValidationError[]).map(({ path: [path], message }) => [
            String(path),
            message,
          ]),
        );
        return;
      } else {
        throw error;
      }
    }

    profilesRef.value = { ...profilesRef.value, [result.profile]: result };
    if (createNew) {
      activeProfileRef.value = result.profile;
    }

    editing = false;
  };

  const deleteConfig = async () => {
    const { ok } = await api.confirm(
      "Delete profile",
      `Do you really want to delete this profile?

Deleting a profile does not delete your add-ons; it simply \
dissociates the add-on folder from instawow.  However, you \
will have to reconcile your add-ons again if you create \
a new profile for this folder and your rollback history \
will be lost.`,
    );
    if (ok) {
      await api.deleteProfile(profileConfig.profile);

      profilesRef.value = ld.omit(profilesRef.value, profileConfig.profile);
      [activeProfileRef.value] = Object.keys(profilesRef.value);

      editing = false;
    }
  };

  const dismissOnEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape" && editing) {
      editing = false;
      event.preventDefault();
    }
  };
</script>

<svelte:window onkeydown={dismissOnEsc} />

<dialog open class="modal" transition:fade={{ duration: 200 }}>
  <form
    class="content"
    onsubmit={(e) => {
      e.preventDefault();
      saveConfig();
    }}
  >
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
        bind:value={profileConfig.profile}
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
        value={profileConfig.addonDir || ""}
      />
      <button
        aria-label="select folder"
        class="form-control"
        type="button"
        onclick={(e) => {
          e.preventDefault();
          selectFolder();
        }}
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
        bind:value={profileConfig.gameFlavour}
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
          onclick={(e) => {
            e.preventDefault();
            deleteConfig();
          }}
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
