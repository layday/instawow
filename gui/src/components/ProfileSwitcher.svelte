<script lang="ts">
  import type { Api, Config } from "../api";
  import { faPencilAlt, faPlusCircle } from "@fortawesome/free-solid-svg-icons";
  import { onMount } from "svelte";
  import { activeProfile, profiles } from "../store";
  import ConfigEditor from "./ConfigEditor.svelte";
  import Icon from "./SvgIcon.svelte";

  export let api: Api;

  let editing: "new" | "existing" | false = false;

  onMount(() => !$activeProfile && (editing = "new"));
</script>

<style lang="scss">
  .profile-switcher-wrapper {
    position: relative;
  }

  .profile-switcher {
    $line-height: 2em;
    $middle-border-radius: $line-height / 6;
    $edge-border-radius: $line-height / 4;

    display: flex;
    font-size: 0.9em;

    button,
    select {
      line-height: $line-height;
      padding: 0 0.5em;
      background-color: var(--inverse-color-10);
      border: 0;
      border-radius: $middle-border-radius;
      -webkit-app-region: no-drag;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: var(--inverse-color-20);
      }
    }

    button {
      width: 2rem;
      margin-left: 4px;

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

<div class="profile-switcher-wrapper">
  {#if editing === 'new'}
    <ConfigEditor bind:editing {api} />
  {:else if editing === 'existing'}
    <ConfigEditor bind:editing {api} />
  {/if}
  <nav class="profile-switcher">
    <select aria-label="profile" bind:value={$activeProfile} disabled={!!editing}>
      {#each Object.keys($profiles) as profile}
        <option value={profile}>{profile}</option>
      {/each}
    </select>
    <button
      aria-label="edit profile"
      title="edit profile"
      on:click={() => (editing = editing === 'existing' ? false : 'existing')}>
      <Icon icon={faPencilAlt} />
    </button>
    <button
      aria-label="add profile"
      title="add profile"
      on:click={() => (editing = editing === 'new' ? false : 'new')}>
      <Icon icon={faPlusCircle} />
    </button>
  </nav>
</div>
