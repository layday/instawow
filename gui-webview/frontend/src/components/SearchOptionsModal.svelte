<script lang="ts">
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import type { Sources } from "../api";
  import { Flavour, Strategy } from "../api";
  import Modal from "./Modal.svelte";
  import type { SearchStrategies } from "./ProfileView.svelte";

  export let show: boolean,
    flavour: Flavour,
    sources: Sources,
    searchFilterInstalled: boolean,
    searchSources: string[],
    searchFromAlias: boolean,
    searchLimit: number,
    searchStartDate: string | null,
    searchStrategies: SearchStrategies;

  const CHECKBOXES = [
    [Strategy.any_flavour, "any flavour"],
    [Strategy.any_release_type, "any release type"],
  ] as const;

  const START_DATE_SUGGESTIONS = [
    { date: "2022-05-31", label: "9.2.5", flavour: Flavour.retail },
    { date: "2020-10-13", label: "9.0.1", flavour: Flavour.retail },
    {
      date: DateTime.now().minus({ days: 1 }).toISODate(),
      label: "yesterday",
      flavour: null,
    },
  ];

  const dispatch = createEventDispatcher<{ [type: string]: void }>();

  const requestSearch = () => {
    dispatch("requestSearch");
    show = false;
  };

  $: if (searchStartDate === "") {
    searchStartDate = null;
  }

  $: console.log(searchStrategies);
</script>

<Modal bind:show>
  <form
    class="content"
    on:submit|preventDefault={() => requestSearch()}
    on:reset={() => dispatch("requestReset")}
  >
    <div class="row form-grid">
      <label for="__search-limit">results:</label>
      <select
        id="__search-limit"
        class="form-control"
        disabled={searchFromAlias}
        bind:value={searchLimit}
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
        disabled={searchFromAlias}
        bind:value={searchSources}
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
        disabled={searchFromAlias}
        bind:value={searchStartDate}
      />
      <ul class="start-date-suggestions">
        {#each START_DATE_SUGGESTIONS as { date, label, flavour: suggestionFlavour }}
          {#if !suggestionFlavour || flavour === suggestionFlavour}
            <li class:disabled={searchFromAlias}>
              <button
                type="button"
                on:click={() => {
                  if (!searchFromAlias) {
                    searchStartDate = date;
                  }
                }}
              >
                {label}</button
              >
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
            bind:checked={searchStrategies[strategy]}
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
        bind:value={searchStrategies[Strategy.version_eq]}
      />
    </div>
    <div class="row input-array">
      <button class="form-control" type="submit">search</button>
      <button class="form-control" type="reset">reset</button>
    </div>
  </form>
</Modal>

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
