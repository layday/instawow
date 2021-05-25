<script lang="ts">
  import type { Sources } from "../api";
  import {
    faFilter,
    faGripLines,
    faLink,
    faStepBackward,
    faStepForward,
  } from "@fortawesome/free-solid-svg-icons";
  import { createEventDispatcher } from "svelte";
  import { fade, fly } from "svelte/transition";
  import { Strategy } from "../api";
  import { View } from "../constants";
  import ProgressIndicator from "./ProgressIndicator.svelte";
  import Icon from "./SvgIcon.svelte";

  export let profile: string,
    sources: Sources,
    activeView: View,
    addonsCondensed: boolean,
    search__terms: string,
    search__filterInstalled: boolean,
    search__fromAlias: boolean,
    search__source: string | null,
    search__strategy: Strategy,
    search__version: string,
    search__isSearching: boolean,
    installed__isModifying: boolean,
    installed__isRefreshing: boolean,
    installed__outdatedAddonCount: number,
    reconcile__isInstalling: boolean,
    reconcile__canStepBackward: boolean,
    reconcile__canStepForward: boolean;

  const dispatch = createEventDispatcher();

  let searchBox: HTMLElement;

  // const modifierKey = __INSTAWOW_PLATFORM__ === "darwin" ? "metaKey" : "ctrlKey";

  // const focusSearchBoxOnMetaF = (e: KeyboardEvent) => {
  //   if (e[modifierKey] && e.code === "KeyF") {
  //     searchBox.focus();
  //   } else if (e[modifierKey] && e.code === "KeyG") {
  //     search__filterInstalled = !search__filterInstalled;
  //   }
  // };

  const handleKeypress = (e: CustomEvent) => {
    if (e.detail.action === "focusSearchBox") {
      searchBox.focus();
    } else if (e.detail.action === "toggleFiltering") {
      search__filterInstalled = !search__filterInstalled;
    }
  };

  window.addEventListener("togaSimulateKeypress", handleKeypress as (e: Event) => void);
</script>

<!-- <svelte:window on:keydown={focusSearchBoxOnMetaF} /> -->

<nav class="addon-list-nav">
  <menu class="view-actions">
    <input
      type="radio"
      id="__radio-googoo-{profile}"
      value={View.Installed}
      bind:group={activeView}
    />
    <label class="segmented-label segment-label--first" for="__radio-googoo-{profile}"
      >installed</label
    >
    <input
      type="radio"
      id="__radio-gaga-{profile}"
      value={View.Reconcile}
      bind:group={activeView}
    />
    <label class="segmented-label" for="__radio-gaga-{profile}">unreconciled</label>
    <button
      aria-label="condense/expand add-on cells"
      disabled={activeView === View.Reconcile}
      on:click={() => (addonsCondensed = !addonsCondensed)}
    >
      <Icon icon={faGripLines} />
    </button>
  </menu>
  <div class="search-wrapper">
    <div class="view-actions">
      <input
        id="__search-filter-installed-{profile}"
        class="hidden"
        type="checkbox"
        bind:checked={search__filterInstalled}
      />
      <label
        for="__search-filter-installed-{profile}"
        aria-label="filter installed add-ons"
        title="filter installed add-ons"
      >
        <Icon icon={faFilter} />
      </label>
    </div>
    <input
      type="search"
      placeholder="search"
      bind:this={searchBox}
      bind:value={search__terms}
      on:keydown
      disabled={activeView === View.Reconcile}
    />
    {#if search__isSearching}
      <div class="progress-indicator" in:fade>
        <ProgressIndicator diameter={18} progress={0} />
      </div>
    {/if}
  </div>
  <menu class="view-actions">
    {#if activeView === View.Installed}
      <button disabled={installed__isRefreshing} on:click={() => dispatch("requestRefresh")}>
        refresh
      </button>
      <button
        disabled={installed__isModifying ||
          installed__isRefreshing ||
          !installed__outdatedAddonCount}
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
        <select aria-label="source" bind:value={search__source}>
          <optgroup label="source">
            <option value={null}>any</option>
            {#each Object.keys(sources) as source}
              <option value={source}>{source}</option>
            {/each}
          </optgroup>
        </select>
      {/if}
      <select aria-label="strategy" bind:value={search__strategy}>
        <optgroup label="strategy">
          {#each Object.values(Strategy) as strategy}
            <option value={strategy}>{strategy}</option>
          {/each}
        </optgroup>
      </select>
      {#if search__strategy === Strategy.version}
        <input
          type="text"
          class="version"
          placeholder="version"
          bind:value={search__version}
          on:keydown
          in:fly={{ duration: 200, x: 64 }}
        />
      {/if}
    {:else if activeView === View.Reconcile}
      {#if reconcile__isInstalling}
        <div class="progress-indicator" in:fade>
          <ProgressIndicator diameter={18} progress={0} />
        </div>
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
  @use "sass:math";

  @import "scss/vars";

  $line-height: 1.8em;
  $middle-border-radius: math.div($line-height, 6);
  $edge-border-radius: math.div($line-height, 4);

  .hidden {
    display: none;
  }

  [type="checkbox"],
  [type="radio"] {
    @extend .hidden;

    &:checked + label {
      background-color: var(--inverse-color-tone-10);
      color: var(--base-color);

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
    font-weight: 600;
  }

  .addon-list-nav {
    @include nav-grid(3);
    margin-bottom: 0.5em;

    button,
    input[type="search"],
    input[type="text"],
    input + label,
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
      margin-left: -1px;
      padding: 0 0.75em;
      transition: all 0.2s;
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
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

    .progress-indicator {
      margin-left: 0.5em;
    }

    & .view-actions > label:last-child {
      line-height: 1.75rem;
      border-bottom-right-radius: 0;
      border-top-right-radius: 0;
    }
  }

  .progress-indicator {
    height: 18px;

    :global(circle) {
      stroke: currentColor;
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
      margin: 0;
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

    :not(:first-child, .segment-label--first) {
      margin-left: 4px;
    }

    select {
      width: 100%;
      padding-right: 1.4rem;
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top calc(50% + 1px) right 7px;
      -webkit-appearance: none;
    }

    .segmented-label {
      ~ .segmented-label {
        margin-left: -1px;
      }
    }

    .version {
      max-width: 4rem;
    }

    :global(.icon) {
      height: 1rem;
      width: 1rem;
      vertical-align: text-bottom;
      fill: var(--inverse-color-tone-10);
    }

    .progress-indicator {
      margin-right: 0.5em;
    }
  }
</style>
