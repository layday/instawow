<script lang="ts">
  import { faStepBackward, faStepForward } from "@fortawesome/free-solid-svg-icons";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";
  import { Strategies } from "../api";
  import { View } from "../constants";
  import Icon from "./SvgIcon.svelte";

  export let activeView: View,
    search__searchTerms: string,
    search__searchStrategy: Exclude<Strategies, "version">,
    search__isSearching: boolean,
    installed__isRefreshing: boolean,
    installed__outdatedAddonCount: number,
    reconcile__isInstalling: boolean,
    reconcile__canStepBackward: boolean,
    reconcile__canStepForward: boolean;

  const dispatch = createEventDispatcher();
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
    input[type="search"],
    label,
    select {
      border: 0;
      background-color: var(--inverse-color-10);
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

    .status-indicator {
      margin-left: 0.5em;
    }
  }

  .status-indicator {
    @include spinner(18px, currentColor);
  }

  .view-switcher {
    @include unstyle-list;
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
    @include unstyle-list;
    display: flex;
    align-items: center;
    font-size: 0.85em;

    button,
    select {
      line-height: $line-height;
      padding: 0 0.7em;
      border-radius: $middle-border-radius;

      + button,
      + select {
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

    select {
      padding-right: 1.4rem;
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top 7px right 7px;
      -webkit-appearance: none;
    }

    .status-indicator {
      margin-right: 0.5em;
    }
  }
</style>

<nav class="addon-list-nav">
  <div class="search-wrapper">
    <input
      type="search"
      placeholder="search"
      bind:value={search__searchTerms}
      on:keydown
      disabled={activeView === View.Reconcile} />
    {#if search__isSearching}
      <div class="status-indicator" transition:fade={{ duration: 200 }} />
    {/if}
  </div>
  <menu class="view-switcher">
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
  </menu>
  <menu class="view-actions">
    {#if activeView === View.Installed}
      <button disabled={installed__isRefreshing} on:click={() => dispatch('requestRefresh')}>
        refresh
      </button>
      <button
        disabled={installed__isRefreshing || !installed__outdatedAddonCount}
        on:click={() => dispatch('requestUpdateAll')}>
        {installed__outdatedAddonCount ? `update ${installed__outdatedAddonCount}` : 'no updates'}
      </button>
    {:else if activeView === View.Search}
      <select aria-label="strategy" bind:value={search__searchStrategy}>
        {#each Object.values(Strategies).filter((s) => s !== 'version') as strategy}
          <option value={strategy}>{strategy}</option>
        {/each}
      </select>
    {:else if activeView === View.Reconcile}
      {#if reconcile__isInstalling}
        <div class="status-indicator" transition:fade={{ duration: 200 }} />
      {/if}
      <button
        aria-label="previous stage"
        title="previous stage"
        disabled={!reconcile__canStepBackward || reconcile__isInstalling}
        on:click={() => dispatch('requestReconcileStepBackward')}>
        <Icon icon={faStepBackward} />
      </button>
      <button
        aria-label="next stage"
        title="next stage"
        disabled={!reconcile__canStepForward || reconcile__isInstalling}
        on:click={() => dispatch('requestReconcileStepForward')}>
        <Icon icon={faStepForward} />
      </button>
      <button
        disabled={reconcile__isInstalling}
        on:click={() => dispatch('requestInstallReconciled')}>
        install
      </button>
      <button
        disabled={reconcile__isInstalling}
        on:click={() => dispatch('requestAutomateReconciliation')}>
        automate
      </button>
    {/if}
  </menu>
</nav>
