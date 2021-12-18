<script lang="ts">
  import { faCog, faFilter, faGripLines, faLink } from "@fortawesome/free-solid-svg-icons";
  import { createEventDispatcher } from "svelte";
  import { ReconciliationStage } from "../api";
  import { View } from "../constants";
  import ProgressIndicator from "./ProgressIndicator.svelte";
  import Icon from "./SvgIcon.svelte";

  export let activeView: View,
    searchTerms: string,
    searchFilterInstalled: boolean,
    searchFromAlias: boolean,
    searchIsDirty: boolean,
    isRefreshing: boolean,
    isModifying: boolean,
    isSearching: boolean,
    installedOutdatedCount: number,
    reconcileInstallationInProgress: boolean,
    reconcileStage: ReconciliationStage;

  const dispatch = createEventDispatcher<{ [type: string]: void }>();

  let searchBox: HTMLInputElement;

  const handleKeypress = (e: CustomEvent) => {
    const { action } = e.detail;
    if (action === "activateViewInstalled") {
      activeView = View.Installed;
    } else if (action === "activateViewReconcile") {
      activeView = View.Reconcile;
    } else if (action === "activateViewSearch") {
      activeView = View.Search;
      searchBox.focus();
    } else if (action === "toggleSearchFilter") {
      searchFilterInstalled = !searchFilterInstalled;
      if (searchFilterInstalled) {
        searchBox.focus();
        if (searchTerms) {
          dispatch("requestSearch");
        }
      } else {
        activeView = View.Installed;
      }
    }
  };
</script>

<svelte:window on:togaSimulateKeypress={handleKeypress} />

<nav class="addon-list-nav">
  <div>
    <menu class="control-set">
      <li class="segmented-control">
        <input
          class="control"
          type="radio"
          id="__radio-googoo"
          value={View.Installed}
          bind:group={activeView}
        />
        <label class="control" for="__radio-googoo">installed</label>
      </li>
      <li class="segmented-control">
        <input
          class="control"
          type="radio"
          id="__radio-gaga"
          value={View.Reconcile}
          bind:group={activeView}
        />
        <label class="control" for="__radio-gaga">unreconciled</label>
      </li>
      <li>
        <button
          class="control"
          aria-label="condense/expand add-on cells"
          disabled={activeView === View.Reconcile}
          on:click={() => dispatch("requestCycleListFormat")}
        >
          <Icon icon={faGripLines} />
        </button>
      </li>
    </menu>
  </div>
  <div class="search">
    <menu class="control-set">
      {#if activeView === View.Reconcile}
        <li>
          <select
            class="control reconciliation-stage-control"
            aria-label="reconciliation stage"
            disabled={reconcileInstallationInProgress}
            bind:value={reconcileStage}
          >
            {#each Object.values(ReconciliationStage) as stage}
              <option value={stage}>{stage}</option>
            {/each}
          </select>
        </li>
      {:else}
        <li>
          <input
            class="control"
            id="__search-filter-installed"
            type="checkbox"
            bind:checked={searchFilterInstalled}
          />
          <label
            class="control"
            for="__search-filter-installed"
            aria-label="filter installed add-ons"
            title="filter installed add-ons"
          >
            <Icon icon={faFilter} />
          </label>
        </li>
        <li>
          <!-- Not type="search" because cursor jumps to end in Safari -->
          <input
            class="control search-control"
            type="text"
            placeholder="search"
            bind:this={searchBox}
            bind:value={searchTerms}
            on:keydown={(e) => e.key === "Enter" && dispatch("requestSearch")}
          />
        </li>
      {/if}
    </menu>
    <div class="progress-indicator" class:hidden={!isSearching}>
      <ProgressIndicator diameter={18} progress={0} />
    </div>
  </div>
  <div>
    <div class="progress-indicator" class:hidden={!reconcileInstallationInProgress}>
      <ProgressIndicator diameter={18} progress={0} />
    </div>
    <menu class="control-set">
      {#if activeView === View.Installed}
        <li>
          <button
            class="control"
            disabled={isRefreshing}
            on:click={() => dispatch("requestRefresh")}
          >
            refresh
          </button>
        </li>
        <li>
          <button
            class="control"
            disabled={isModifying || isRefreshing || !installedOutdatedCount}
            on:click={() => dispatch("requestUpdateAll")}
          >
            {installedOutdatedCount ? `update ${installedOutdatedCount}` : "no updates"}
          </button>
        </li>
      {:else if activeView === View.Search}
        <li>
          <input
            class="control"
            id="__interpret-as-uri"
            type="checkbox"
            bind:checked={searchFromAlias}
            on:change={() => dispatch("requestSearch")}
          />
          <label
            class="control"
            for="__interpret-as-uri"
            aria-label="interpret query as add-on URI"
            title="interpret query as add-on URI"
          >
            <Icon icon={faLink} />
          </label>
        </li>
        <li>
          <button
            class="control"
            class:dirty={searchIsDirty}
            aria-label="show search options"
            on:click={() => dispatch("requestShowSearchOptionsModal")}
          >
            <Icon icon={faCog} />
          </button>
        </li>
      {:else if activeView === View.Reconcile}
        <li>
          <button
            class="control"
            disabled={reconcileInstallationInProgress}
            on:click={() => dispatch("requestInstallReconciled")}
          >
            install
          </button>
        </li>
        <li>
          <button
            class="control"
            disabled={reconcileInstallationInProgress}
            on:click={() => dispatch("requestAutomateReconciliation")}
          >
            automate
          </button>
        </li>
      {/if}
    </menu>
  </div>
</nav>

<style lang="scss">
  @use "sass:math";

  @use "scss/vars";

  $line-height: 1.8em;
  $middle-border-radius: math.div($line-height, 6);
  $edge-border-radius: math.div($line-height, 4);

  %center-flex {
    display: flex;
    align-items: center;
  }

  menu {
    @extend %unstyle-list;
    font-weight: 500;
  }

  .addon-list-nav {
    @extend %nav-grid;
    grid-template-columns: repeat(3, 1fr);
    height: 3rem;

    > div {
      @extend %center-flex;
    }
  }

  .search {
    .control-set {
      font-size: 1rem;
    }

    .search-control {
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);

      &,
      &::-webkit-search-cancel-button {
        -webkit-appearance: none;
        appearance: none;
      }

      &:not(:focus) {
        text-align: center;
      }
    }
  }

  .progress-indicator {
    height: 18px;
    line-height: 18px;
    margin: 0 0.5rem;

    :global(circle) {
      stroke: currentColor;
    }

    &.hidden {
      visibility: hidden;
    }
  }

  .control {
    display: block;
    min-width: min-content;
    border: 0;
    transition: all 0.2s;
    line-height: $line-height;
    margin: 0;
    padding: 0 0.7em;
    border-radius: $middle-border-radius;
    white-space: nowrap;

    &:disabled {
      opacity: 0.5;
    }

    &:hover:not(:disabled) {
      background-color: var(--inverse-color-alpha-05);
    }

    &:focus {
      background-color: var(--inverse-color-alpha-10);
    }

    &[type="checkbox"],
    &[type="radio"] {
      position: absolute;
      opacity: 0;

      &:checked + label {
        background-color: var(--inverse-color-tone-b) !important;
        color: var(--base-color);

        :global(.icon) {
          fill: var(--base-color);
        }
      }

      &:disabled + label {
        opacity: 0.5;
      }

      &:focus + label {
        background-color: var(--inverse-color-alpha-10);
      }
    }

    &.dirty {
      @include vars.striped-background(-45deg, rgba(salmon, 0.5));
    }

    &.reconciliation-stage-control {
      width: 100%;
      padding-right: 1.4rem;
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top calc(50% + 1px) right 7px;
    }

    :global(.icon) {
      height: 1rem;
      width: 1rem;
      vertical-align: text-bottom;
      fill: var(--inverse-color-tone-b);
    }
  }

  .control-set {
    @extend %center-flex;
    font-size: 0.85em;

    li {
      &:not(:first-child) {
        margin-left: 4px;
      }

      &.segmented-control {
        ~ .segmented-control {
          margin-left: -1px;
        }
      }

      &:first-child .control {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-child .control {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }
    }
  }
</style>
