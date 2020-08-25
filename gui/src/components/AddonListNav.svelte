<script lang="ts">
  import { faArrowCircleLeft, faArrowCircleRight } from "@fortawesome/free-solid-svg-icons";
  import { fade } from "svelte/transition";
  import { View } from "./ProfileView.svelte";
  import Icon from "./SvgIcon.svelte";

  export let searchTerms: string,
    activeView: View,
    refresh: () => Promise<void>,
    addonUpdates: number,
    searchesInProgress: number,
    refreshInProgress: boolean;
</script>

<style lang="scss">
  @import "vars";

  $line-height: 1.8em;
  $middle-border-radius: $line-height / 6;
  $edge-border-radius: $line-height / 4;

  .addon-list-nav {
    @include nav-grid(3);
    margin-bottom: 0.5em;

    button,
    label,
    [type="search"] {
      background-color: var(--inverse-color-10);
      border: 0;
      transition: background-color 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: var(--inverse-color-20);
      }
    }
  }

  .search-wrapper {
    display: flex;
    align-items: center;
    width: 100%;

    [type="search"] {
      flex-basis: calc(100% - 2em);
      line-height: 1.75em;
      padding: 0 0.75em;
      transition: all 0.2s;
      border-radius: 2em;

      &,
      &::-webkit-search-cancel-button {
        -webkit-appearance: none;
      }
    }
  }

  .search-status-indicator {
    @include spinner(18px, var(--inverse-color));
    margin-left: 0.5em;
  }

  .view-switcher {
    display: flex;
    font-size: 0.85em;

    [type="radio"] {
      display: none;

      &:checked + label {
        background-color: var(--inverse-color);
        color: var(--base-color);
        font-weight: 500;
      }
    }

    label {
      line-height: $line-height;
      padding: 0 0.7em;

      ~ label {
      }

      &:first-of-type {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-of-type {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }
    }
  }

  .view-actions {
    display: flex;
    font-size: 0.85em;

    button {
      line-height: $line-height;
      padding: 0 0.7em;
      border-radius: $middle-border-radius;

      + button {
        margin-left: 4px;
      }

      &:first-child {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-child {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }

      :global(.icon) {
        height: 16px;
        width: 16px;
        vertical-align: text-bottom;
        fill: var(--inverse-color);
      }
    }
  }
</style>

<nav class="addon-list-nav">
  <div class="search-wrapper">
    <input
      type="search"
      placeholder="Search"
      bind:value={searchTerms}
      disabled={activeView === View.Reconcile} />
    {#if searchesInProgress}
      <div class="search-status-indicator" transition:fade={{ duration: 200 }} />
    {/if}
  </div>
  <div class="view-switcher">
    <input
      type="radio"
      name="view-switcher"
      id="__radioGoogoo"
      value={View.Installed}
      bind:group={activeView} />
    <label for="__radioGoogoo">installed</label>
    <input
      type="radio"
      name="view-switcher"
      id="__radioGaga"
      value={View.Reconcile}
      bind:group={activeView} />
    <label for="__radioGaga">unreconciled</label>
  </div>
  <div class="view-actions">
    {#if activeView === View.Installed}
      <button disabled={refreshInProgress} on:click={() => refresh()}>refresh</button>
      <button disabled={refreshInProgress || !addonUpdates}>
        {addonUpdates ? `update ${addonUpdates}` : 'no updates'}
      </button>
    {:else if activeView == View.Reconcile}
      <button>
        <Icon icon={faArrowCircleLeft} />
      </button>
      <button>install selections</button>
      <button>
        <Icon icon={faArrowCircleRight} />
      </button>
    {/if}
  </div>
</nav>
