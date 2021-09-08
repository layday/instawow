<script lang="ts">
  import { faCog, faPlus } from "@fortawesome/free-solid-svg-icons";
  import { onMount } from "svelte";
  import { activeProfile, profiles } from "../store";
  import ConfigEditor from "./ConfigEditor.svelte";
  import Icon from "./SvgIcon.svelte";

  let editing: "new" | "existing" | false = false;

  onMount(() => !$activeProfile && (editing = "new"));
</script>

<div class="profile-switcher-wrapper">
  {#if editing === "new"}
    <ConfigEditor bind:editing />
  {:else if editing === "existing"}
    <ConfigEditor bind:editing />
  {/if}
  <div class="profile-switcher">
    <select aria-label="profile" bind:value={$activeProfile} disabled={!!editing}>
      {#each [...$profiles.keys()] as profile (profile)}
        <option value={profile}>{profile}</option>
      {/each}
    </select>
    <button
      aria-label="edit profile"
      title="edit profile"
      disabled={!$activeProfile}
      on:click={() => (editing = editing === "existing" ? false : "existing")}
    >
      <Icon icon={faCog} />
    </button>
    <button
      aria-label="add profile"
      title="add profile"
      on:click={() => (editing = editing === "new" ? false : "new")}
    >
      <Icon icon={faPlus} />
    </button>
  </div>
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
    font-size: 0.9em;

    button,
    select {
      line-height: $line-height;
      margin: 0;
      padding: 0 0.5em;
      border: 0;
      border-radius: $middle-border-radius;
      transition: all 0.2s;

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
      width: 2rem;
      margin-left: 4px;

      :global(.icon) {
        height: 1rem;
        fill: var(--inverse-color-tone-20);
      }
    }

    select {
      padding-left: 0.65em;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top calc(50% + 1px) right 7px;
      min-width: 200px;
      font-weight: 500;
      -webkit-appearance: none;
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
