<script lang="ts">
  import { faCog } from "@fortawesome/free-solid-svg-icons";
  import { getContext } from "svelte";
  import {
    ACTIVE_PROFILE_KEY,
    PROFILES_KEY,
    type ActiveProfileRef,
    type ProfilesRef,
  } from "../stores/profiles.svelte";
  import ConfigModalContents from "./ConfigModalContents.svelte";
  import ProfileConfigEditor from "./ProfileConfigEditor.svelte";
  import Icon from "./SvgIcon.svelte";
  import Modal from "./modal/Modal.svelte";

  const profilesRef = getContext<ProfilesRef>(PROFILES_KEY);
  const activeProfileRef = getContext<ActiveProfileRef>(ACTIVE_PROFILE_KEY);

  let editing = $state<"new" | "existing" | "auth" | false>(false);

  $effect(() => {
    if (!activeProfileRef.value) {
      editing = "new";
    }
  });
</script>

<div class="profile-switcher-wrapper">
  <div class="profile-switcher">
    <button
      aria-label="configure access tokens"
      onclick={() => (editing = editing === "auth" ? false : "auth")}
    >
      <Icon icon={faCog} />
    </button>

    <select aria-label="profile" bind:value={activeProfileRef.value} disabled={!!editing}>
      {#each Object.keys(profilesRef.value) as profile (profile)}
        <option value={profile}>{profile}</option>
      {/each}
    </select>

    <button
      aria-label="edit profile"
      disabled={!activeProfileRef.value}
      onclick={() => (editing = editing === "existing" ? false : "existing")}
    >
      edit
    </button>
    <button aria-label="add profile" onclick={() => (editing = editing === "new" ? false : "new")}>
      add
    </button>
  </div>

  {#if editing === "new"}
    <ProfileConfigEditor bind:editing />
  {:else if editing === "existing"}
    <ProfileConfigEditor bind:editing />
  {:else if editing === "auth"}
    <Modal onHide={() => (editing = false)}>
      <ConfigModalContents />
    </Modal>
  {/if}
</div>

<style lang="scss">
  @use "sass:math";

  .profile-switcher-wrapper {
    position: relative;
  }

  .profile-switcher {
    $line-height: 2em;
    $middle-border-radius: math.div($line-height, 6);
    $edge-border-radius: math.div($line-height, 4);

    display: flex;
    font-size: 0.95em;

    > :not(:first-child) {
      margin-left: 4px;
    }

    button,
    select {
      line-height: $line-height;
      margin: 0;
      padding: 0 0.5em;
      border: 0;
      border-radius: $middle-border-radius;
      transition: all 0.2s;
      font-weight: 500;

      &:disabled {
        opacity: 0.5;
      }

      &:hover:not(:disabled) {
        background-color: var(--inverse-color-alpha-05);
      }

      &:focus {
        background-color: var(--inverse-color-alpha-20);
      }
    }

    button {
      display: flex;
      place-items: center;
    }

    select {
      padding-left: 0.65em;
      padding-right: 1.25rem;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top calc(50% + 1px) right 7px;
      min-width: 180px;
    }

    :first-child {
      border-top-left-radius: $edge-border-radius;
      border-bottom-left-radius: $edge-border-radius;
    }

    :last-child {
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
    }

    :global(.icon) {
      height: 1rem;
      width: 1rem;
      vertical-align: text-bottom;
      fill: var(--inverse-color-tone-b);
    }
  }
</style>
