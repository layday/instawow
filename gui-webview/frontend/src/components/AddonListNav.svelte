<script lang="ts">
  import type { Sources } from "../api";
  import { faCog, faFilter, faGripLines, faLink } from "@fortawesome/free-solid-svg-icons";
  import { createEventDispatcher } from "svelte";
  import { fade, fly } from "svelte/transition";
  import { ReconciliationStage, Strategy } from "../api";
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
    search__isSearching: boolean,
    installed__isModifying: boolean,
    installed__isRefreshing: boolean,
    installed__outdatedAddonCount: number,
    reconcile__isInstalling: boolean,
    reconcile__stage: ReconciliationStage;

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
    if (e.detail.action === "activateViewInstalled") {
      activeView = View.Installed;
    } else if (e.detail.action === "activateViewReconcile") {
      activeView = View.Reconcile;
    } else if (e.detail.action === "activateViewSearch") {
      activeView = View.Search;
      searchBox.focus();
    } else if (e.detail.action === "toggleSearchFilter") {
      search__filterInstalled = !search__filterInstalled;
      if (search__filterInstalled) {
        searchBox.focus();
        if (search__terms) {
          dispatch("requestSearch");
        }
      } else {
        activeView = View.Installed;
      }
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
      on:keydown={(e) => e.key === "Enter" && dispatch("requestSearch")}
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
        on:change={() => dispatch("requestSearch")}
      />
      <label
        for="__interpret-as-uri-{profile}"
        aria-label="interpret query as add-on URI"
        title="interpret query as add-on URI"
      >
        <Icon icon={faLink} />
      </label>
      <button
        aria-label="show search options"
        on:click={() => dispatch("requestShowSearchOptionsModal")}
      >
        <Icon icon={faCog} />
      </button>
    {:else if activeView === View.Reconcile}
      {#if reconcile__isInstalling}
        <div class="progress-indicator" in:fade>
          <ProgressIndicator diameter={18} progress={0} />
        </div>
      {/if}
      <select
        aria-label="reconciliation stage"
        disabled={reconcile__isInstalling}
        bind:value={reconcile__stage}
      >
        <optgroup label="stage">
          {#each Object.values(ReconciliationStage) as stage}
            <option value={stage}>{stage}</option>
          {/each}
        </optgroup>
      </select>
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
      background-color: var(--inverse-color-tone-20) !important;
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
    font-weight: 500;
  }

  .addon-list-nav {
    @include nav-grid(3);
    margin-bottom: 0.5em;

    button,
    input[type="search"],
    input[type="text"],
    input + label,
    select {
      min-width: min-content;
      border: 0;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:hover:not(:disabled) {
        background-color: var(--inverse-color-alpha-05);
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
      margin-left: 4px;
      margin-right: 0.5rem;
      padding: 0 0.75em;
      transition: all 0.2s;
      border-top-left-radius: $middle-border-radius;
      border-bottom-left-radius: $middle-border-radius;
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
      background-color: transparent;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);

      &,
      &::-webkit-search-cancel-button {
        -webkit-appearance: none;
      }

      &:not(:focus) {
        text-align: center;
      }
    }

    & .view-actions > label:last-child {
      line-height: 1.75rem;
      border-top-right-radius: $middle-border-radius;
      border-bottom-right-radius: $middle-border-radius;
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

    :not(:first-child):not(.segment-label--first) {
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
      fill: var(--inverse-color-tone-20);
    }

    .progress-indicator {
      margin-right: 0.5em;
    }
  }
</style>
