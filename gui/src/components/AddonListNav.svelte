<script lang="ts">
  import type { Sources } from "../api";
  import {
    faGripLines,
    faLink,
    faStepBackward,
    faStepForward,
  } from "@fortawesome/free-solid-svg-icons";
  import { createEventDispatcher } from "svelte";
  import { fade, fly } from "svelte/transition";
  import { Strategy } from "../api";
  import { View } from "../constants";
  import Icon from "./SvgIcon.svelte";

  export let profile: string,
    sources: Sources,
    activeView: View,
    addonsCondensed: boolean,
    search__searchTerms: string,
    search__fromAlias: boolean,
    search__searchSource: string | null,
    search__searchStrategy: Strategy,
    search__searchVersion: string,
    search__isSearching: boolean,
    installed__isRefreshing: boolean,
    installed__outdatedAddonCount: number,
    reconcile__isInstalling: boolean,
    reconcile__canStepBackward: boolean,
    reconcile__canStepForward: boolean;

  const dispatch = createEventDispatcher();
</script>

<nav class="addon-list-nav">
  <div class="view-controls">
    <menu>
      <input
        type="radio"
        id="__radio-googoo-{profile}"
        value={View.Installed}
        bind:group={activeView}
      />
      <label for="__radio-googoo-{profile}">installed</label>
      <input
        type="radio"
        id="__radio-gaga-{profile}"
        value={View.Reconcile}
        bind:group={activeView}
      />
      <label for="__radio-gaga-{profile}">unreconciled</label>
    </menu>
    <menu class="view-actions">
      <button
        aria-label="condense/expand add-on cells"
        disabled={activeView === View.Reconcile}
        on:click={() => (addonsCondensed = !addonsCondensed)}
      >
        <Icon icon={faGripLines} />
      </button>
    </menu>
  </div>
  <div class="search-wrapper">
    <input
      type="search"
      placeholder="search"
      bind:value={search__searchTerms}
      on:keydown
      disabled={activeView === View.Reconcile}
    />
    {#if search__isSearching}
      <div class="status-indicator" transition:fade={{ duration: 200 }} />
    {/if}
  </div>
  <menu class="view-actions">
    {#if activeView === View.Installed}
      <button disabled={installed__isRefreshing} on:click={() => dispatch("requestRefresh")}>
        refresh
      </button>
      <button
        disabled={installed__isRefreshing || !installed__outdatedAddonCount}
        on:click={() => dispatch("requestUpdateAll")}
      >
        {installed__outdatedAddonCount ? `update ${installed__outdatedAddonCount}` : "no updates"}
      </button>
    {:else if activeView === View.Search}
      <input
        id="__interpret-as-uri-{profile}"
        class="hidden"
        type="checkbox"
        bind:checked={search__fromAlias}
      />
      <label
        for="__interpret-as-uri-{profile}"
        aria-label="interpret query as an add-on URI"
        title="interpret query as an add-on URI"
      >
        <Icon icon={faLink} />
      </label>
      {#if !search__fromAlias}
        <select
          aria-label="source"
          bind:value={search__searchSource}
          in:fly={{ duration: 200, x: 64 }}
        >
          <option value={null}>any</option>
          {#each Object.keys(sources) as source}
            <option value={source}>{source}</option>
          {/each}
        </select>
      {/if}
      <select aria-label="strategy" bind:value={search__searchStrategy}>
        {#each Object.values(Strategy) as strategy}
          <option value={strategy}>{strategy}</option>
        {/each}
      </select>
      {#if search__searchStrategy === Strategy.version}
        <input
          type="text"
          class="version"
          placeholder="version"
          bind:value={search__searchVersion}
          on:keydown
          in:fly={{ duration: 200, x: 64 }}
        />
      {/if}
    {:else if activeView === View.Reconcile}
      {#if reconcile__isInstalling}
        <div class="status-indicator" transition:fade={{ duration: 200 }} />
      {/if}
      <button
        aria-label="previous stage"
        title="previous stage"
        disabled={!reconcile__canStepBackward || reconcile__isInstalling}
        on:click={() => dispatch("requestReconcileStepBackward")}
      >
        <Icon icon={faStepBackward} />
      </button>
      <button
        aria-label="next stage"
        title="next stage"
        disabled={!reconcile__canStepForward || reconcile__isInstalling}
        on:click={() => dispatch("requestReconcileStepForward")}
      >
        <Icon icon={faStepForward} />
      </button>
      <button
        disabled={reconcile__isInstalling}
        on:click={() => dispatch("requestInstallReconciled")}
      >
        install
      </button>
      <button
        disabled={reconcile__isInstalling}
        on:click={() => dispatch("requestAutomateReconciliation")}
      >
        automate
      </button>
    {/if}
  </menu>
</nav>

<style lang="scss">
  @import "scss/vars";

  $line-height: 1.8em;
  $middle-border-radius: $line-height / 6;
  $edge-border-radius: $line-height / 4;

  .hidden {
    display: none;
  }

  [type="checkbox"],
  [type="radio"] {
    @extend .hidden;

    &:checked + label {
      background-color: var(--inverse-color-tone-10);
      color: var(--base-color);
      font-weight: 500;

      :global(.icon) {
        fill: var(--base-color);
      }
    }

    &:disabled + label {
      opacity: 0.5;
    }
  }

  menu {
    @include unstyle-list;
  }

  .addon-list-nav {
    @include nav-grid(3);
    margin-bottom: 0.5em;

    button,
    input[type="search"],
    input[type="text"],
    label,
    select {
      border: 0;
      background-color: var(--inverse-color-alpha-05);
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: var(--inverse-color-alpha-10);
        box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-20);
      }
    }
  }

  .search-wrapper {
    display: flex;
    align-items: center;
    width: 100%;

    input[type="search"] {
      flex-basis: calc(100% - 2em);
      line-height: 1.75em;
      padding: 0 0.75em;
      transition: all 0.2s;
      border-radius: $edge-border-radius;
      background-color: transparent;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-20);

      &,
      &::-webkit-search-cancel-button {
        -webkit-appearance: none;
      }

      &:not(:focus) {
        text-align: center;
      }
    }

    .status-indicator {
      margin-left: 0.5em;
    }
  }

  .status-indicator {
    @include spinner(18px, currentColor);
  }

  .view-controls {
    display: flex;

    menu {
      display: flex;
      font-size: 0.85rem;

      + menu {
        margin-left: 4px;
      }

      label {
        line-height: $line-height;
        padding: 0 0.7em;

        &:first-of-type {
          border-top-left-radius: $middle-border-radius;
          border-bottom-left-radius: $middle-border-radius;
        }

        &:last-of-type {
          border-top-right-radius: $middle-border-radius;
          border-bottom-right-radius: $middle-border-radius;
        }

        ~ label {
          margin-left: -1px;
        }
      }

      &:first-child label:first-of-type {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-child label:last-of-type {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }

      &.view-actions > button:first-child {
        border-top-left-radius: $middle-border-radius;
        border-bottom-left-radius: $middle-border-radius;
      }
    }
  }

  .view-actions {
    display: flex;
    align-items: center;
    font-size: 0.85em;

    > button,
    > input,
    > label,
    > select {
      line-height: $line-height;
      padding: 0 0.7em;
      border-radius: $middle-border-radius;

      &:first-child {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-child {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }
    }

    > .hidden:first-child + label {
      border-top-left-radius: $edge-border-radius;
      border-bottom-left-radius: $edge-border-radius;
    }

    :not(:first-child) {
      margin-left: 4px;
    }

    select {
      padding-right: 1.4rem;
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top calc(50% + 1px) right 7px;
      -webkit-appearance: none;
    }

    .version {
      max-width: 4rem;
    }

    :global(.icon) {
      height: 1rem;
      width: 1rem;
      vertical-align: text-bottom;
      fill: var(--inverse-color);
    }

    .status-indicator {
      margin-right: 0.5em;
    }
  }
</style>
