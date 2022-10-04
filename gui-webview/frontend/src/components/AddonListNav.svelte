<script lang="ts">
  import { faExchange, faFilter, faSlidersH, faThList } from "@fortawesome/free-solid-svg-icons";
  import { createEventDispatcher } from "svelte";
  import { ReconciliationStage } from "../api";
  import { View } from "../constants";
  import ProgressIndicator from "./ProgressIndicator.svelte";
  import Icon from "./SvgIcon.svelte";

  export let activeView: View,
    searchTerms: string,
    searchFilterInstalled: boolean,
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
          id="__radio-installed"
          value={View.Installed}
          bind:group={activeView}
        />
        <label class="control" for="__radio-installed">installed</label>
      </li>
      <li class="segmented-control">
        <input
          class="control"
          type="radio"
          id="__radio-unreconciled"
          value={View.Reconcile}
          bind:group={activeView}
        />
        <label class="control" for="__radio-unreconciled">unreconciled</label>
      </li>
      {#if activeView === View.Installed || activeView === View.ReconcileInstalled}
        <li>
          <input
            class="control"
            id="__radio-reconcile-installed"
            type="radio"
            value={View.ReconcileInstalled}
            bind:group={activeView}
          />
          <label
            class="control"
            for="__radio-reconcile-installed"
            aria-label="change add-on sources"
            title="change add-on sources"
          >
            <Icon icon={faExchange} />
          </label>
        </li>
      {/if}
      {#if activeView !== View.Reconcile && activeView !== View.ReconcileInstalled}
        <li>
          <button
            class="control"
            aria-label="condense/expand add-on cells"
            title="condense/expand add-on cells"
            on:click={() => dispatch("requestCycleListFormat")}
          >
            <Icon icon={faThList} />
          </button>
        </li>
      {/if}
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
      {:else if activeView !== View.ReconcileInstalled}
        <li>
          <input
            class="control"
            id="__search-installed"
            type="checkbox"
            bind:checked={searchFilterInstalled}
          />
          <label
            class="control"
            for="__search-installed"
            aria-label="search installed add-ons"
            title="search installed add-ons"
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
    {#if isSearching}
      <div class="progress-indicator">
        <ProgressIndicator diameter={18} progress={0} />
      </div>
    {/if}
  </div>
  <div>
    {#if reconcileInstallationInProgress}
      <div class="progress-indicator">
        <ProgressIndicator diameter={18} progress={0} />
      </div>
    {/if}
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
      {:else if activeView === View.Search || activeView === View.FilterInstalled}
        <li>
          <button
            class="control"
            class:dirty={searchIsDirty}
            aria-label="show search options"
            on:click={() => dispatch("requestShowSearchOptionsModal")}
          >
            <Icon icon={faSlidersH} />
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
      {:else if activeView === View.ReconcileInstalled}
        <li>
          <button
            class="control"
            disabled={reconcileInstallationInProgress}
            on:click={() => dispatch("requestInstallReconciledInstalled")}
          >
            switch sources
          </button>
        </li>
      {/if}
    </menu>
  </div>
</nav>

<style lang="scss">
  @use "sass:math";

  @use "scss/vars";

  $line-height: 1.875em;
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
    .search-control {
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);
      font-size: 1rem;

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
