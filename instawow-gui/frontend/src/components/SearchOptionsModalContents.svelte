<script lang="ts">
  import { DateTime } from "luxon";
  import { getContext } from "svelte";
  import type { Sources } from "../api";
  import { Flavour, Strategy } from "../api";
  import type { SearchOptions } from "./Profile.svelte";
  import type { ModalHandle } from "./modal/Modal.svelte";

  let {
    flavour,
    sources,
    searchFilterInstalled,
    searchIsFromAlias,
    searchOptions = $bindable(),
    onRequestReset,
    onRequestSearch,
  }: {
    flavour: Flavour;
    sources: Sources;
    searchFilterInstalled: boolean;
    searchIsFromAlias: boolean;
    searchOptions: SearchOptions;
    onRequestReset: () => void;
    onRequestSearch: () => void;
  } = $props();

  const CHECKBOXES = [
    [Strategy.AnyFlavour, "any flavour"],
    [Strategy.AnyReleaseType, "any release type"],
  ] as const;

  const START_DATE_SUGGESTIONS = [
    { date: "2024-01-16", label: "10.2.5", flavour: Flavour.Retail },
    {
      date: DateTime.now().minus({ days: 1 }).toISODate(),
      label: "yesterday",
      flavour: null,
    },
  ];

  const { hide } = getContext<ModalHandle>("modal");

  const requestSearch = (event: Event) => {
    event.preventDefault();

    onRequestSearch();
    hide();
  };
</script>

<form class="content" onsubmit={requestSearch} onreset={() => onRequestReset()}>
  <div class="row form-grid">
    <label for="__search-limit">results:</label>
    <select
      id="__search-limit"
      class="form-control"
      disabled={searchIsFromAlias}
      bind:value={searchOptions.limit}
    >
      <option value={20}>20</option>
      <option value={50}>50</option>
      <option value={100}>100</option>
    </select>
    <label for="__search-source">sources:</label>
    <select
      id="__search-source"
      class="form-control"
      multiple
      disabled={searchIsFromAlias}
      bind:value={searchOptions.sources}
    >
      {#each Object.entries(sources) as [source, { name }]}
        <option value={source}>{name}</option>
      {/each}
    </select>
    <label for="__search-start-date">updated on/after:</label>
    <input
      type="text"
      id="__search-start-date"
      class="form-control"
      placeholder="YYYY-MM-DD"
      disabled={searchIsFromAlias}
      bind:value={searchOptions.startDate}
    />
    <ul class="start-date-suggestions">
      {#each START_DATE_SUGGESTIONS as { date, label, flavour: suggestionFlavour }}
        {#if !suggestionFlavour || flavour === suggestionFlavour}
          <li class:disabled={searchIsFromAlias}>
            <button
              type="button"
              onclick={() => {
                if (!searchIsFromAlias) {
                  searchOptions.startDate = date;
                }
              }}
            >
              {label}
            </button>
          </li>
        {/if}
      {/each}
    </ul>
    {#each CHECKBOXES as [strategy, label]}
      <label class="control" for="__{strategy}-control">{label}:</label>
      <div class="form-control checkbox-container">
        <input
          id="__{strategy}-control"
          type="checkbox"
          disabled={searchFilterInstalled}
          bind:checked={searchOptions.strategies[strategy]}
        />
      </div>
    {/each}
    <label class="control" for="__version-control">version:</label>
    <input
      id="__version-control"
      type="text"
      class="form-control"
      placeholder="version"
      aria-label="version"
      disabled={searchFilterInstalled}
      bind:value={searchOptions.strategies[Strategy.VersionEq]}
    />
  </div>
  <div class="row input-array">
    <button class="form-control" type="submit">search</button>
    <button class="form-control" type="reset">reset</button>
  </div>
</form>

<style lang="scss">
  @use "scss/vars";

  form {
    .form-grid {
      display: grid;
      grid-template-columns: 1fr 2fr;
      column-gap: 0.5rem;
      row-gap: 0.5rem;
    }

    label {
      line-height: vars.$modal-form-el-line-height;
      color: var(--inverse-color-tone-a);
      text-align: right;
    }

    .start-date-suggestions {
      @extend %unstyle-list;
      display: inline-flex;
      gap: 0.2rem;
      grid-column-start: 2;
      margin-top: -0.3em;
      font-size: 0.8em;
      font-weight: 600;

      li {
        button {
          cursor: pointer;
          margin: 0;
          padding: 0.2rem 0.4rem;
          border: 0;
          border-radius: vars.$modal-middle-border-radius;
          background-color: var(--inverse-color-tone-b);
          color: var(--base-color);
        }

        &.disabled button {
          cursor: default;
          opacity: 0.5;
        }

        &:first-child button {
          border-top-left-radius: vars.$modal-edge-border-radius;
          border-bottom-left-radius: vars.$modal-edge-border-radius;
        }

        &:last-child button {
          border-top-right-radius: vars.$modal-edge-border-radius;
          border-bottom-right-radius: vars.$modal-edge-border-radius;
        }
      }
    }
  }

  .form-control.checkbox-container {
    background-color: transparent;
    padding-left: 0;
  }
</style>
