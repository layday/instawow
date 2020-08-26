<script lang="ts">
  import { faFolderPlus, faPencilAlt } from "@fortawesome/free-solid-svg-icons";
  import { activeProfile, profiles } from "../store";
  import Icon from "./SvgIcon.svelte";
</script>

<style lang="scss">
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

      &:focus {
        background-color: var(--inverse-color-20);
      }
    }

    button {
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

<nav class="profile-switcher">
  <select bind:value={$activeProfile}>
    {#each $profiles as profile}
      <option value={profile}>{profile}</option>
    {/each}
  </select>
  <button label="edit profile" title="edit profile">
    <Icon icon={faPencilAlt} />
  </button>
  <button label="add profile" title="add profile">
    <Icon icon={faFolderPlus} />
  </button>
</nav>
