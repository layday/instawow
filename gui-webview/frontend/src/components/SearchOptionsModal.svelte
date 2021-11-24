<script lang="ts">
  import type { Sources } from "../api";
  import { Flavour, Strategy } from "../api";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { fly, scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: boolean,
    sources: Sources,
    flavour: Flavour,
    searchSources: string[],
    searchFromAlias: boolean,
    searchStartDate: string | null,
    searchStrategy: Strategy,
    searchVersion: string,
    searchLimit: number;

  const startDateSuggestions = [
    { date: "2021-11-02", label: "9.1.5", flavour: Flavour.retail },
    { date: "2020-10-13", label: "9.0.1", flavour: Flavour.retail },
    {
      date: DateTime.now().minus({ days: 1 }).toISODate(),
      label: "yesterday",
      flavour: null,
    },
  ];

  const dispatch = createEventDispatcher();

  const requestSearch = () => {
    dispatch("requestSearch");
    show = false;
  };
</script>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <form
      class="content"
      on:submit|preventDefault={() => requestSearch()}
      on:reset={() => dispatch("requestReset")}
    >
      <div class="row form-grid">
        <label for="__search-limit">results:</label>
        <select id="__search-limit" disabled={searchFromAlias} bind:value={searchLimit}>
          <option value={20}>20</option>
          <option value={50}>50</option>
          <option value={100}>100</option>
        </select>
        <label for="__search-source">sources:</label>
        <select
          id="__search-source"
          multiple
          disabled={searchFromAlias}
          bind:value={searchSources}
        >
          {#each Object.values(sources) as { source, name }}
            <option value={source}>{name}</option>
          {/each}
        </select>
        <label for="__search-start-date">updated on/after:</label>
        <input
          type="text"
          id="__search-start-date"
          placeholder="YYYY-MM-DD"
          disabled={searchFromAlias}
          bind:value={searchStartDate}
        />
        <ul class="start-date-suggestions">
          {#each startDateSuggestions as { date, label, flavour: suggestionFlavour }}
            {#if !suggestionFlavour || flavour === suggestionFlavour}
              <li
                class:disabled={searchFromAlias}
                on:click={() => !searchFromAlias && (searchStartDate = date)}
              >
                {label}
              </li>
            {/if}
          {/each}
        </ul>
        <label for="__search-strategy">strategy:</label>
        <select id="__search-strategy" bind:value={searchStrategy}>
          {#each Object.values(Strategy) as strategy}
            <option value={strategy}>{strategy}</option>
          {/each}
        </select>
        {#if searchStrategy === Strategy.version}
          <input
            type="text"
            class="version"
            placeholder="version"
            aria-label="version"
            bind:value={searchVersion}
            in:fly={{ duration: 200, y: -64 }}
          />
        {/if}
      </div>
      <div class="row input-array">
        <button type="submit">search</button>
        <button type="reset">reset</button>
      </div>
    </form>
  </dialog>
</Modal>

<style lang="scss">
  @use "scss/modal";

  form {
    .form-grid {
      display: grid;
      grid-template-columns: 1fr 2fr;
      column-gap: 0.5rem;
      row-gap: 0.5rem;
    }

    label {
      line-height: modal.$form-el-line-height;
      color: var(--inverse-color-tone-10);
      text-align: right;
    }

    .start-date-suggestions {
      @extend %unstyle-list;
      display: inline-flex;
      gap: 0.2rem;
      font-size: 0.8em;
      font-weight: 600;

      li {
        cursor: pointer;
        padding: 0.2rem 0.4rem;
        border-radius: modal.$middle-border-radius;
        background-color: var(--inverse-color-tone-20);
        color: var(--base-color);

        &.disabled {
          cursor: default;
          opacity: 0.5;
        }

        &:first-child {
          border-top-left-radius: modal.$edge-border-radius;
          border-bottom-left-radius: modal.$edge-border-radius;
        }

        &:last-child {
          border-top-right-radius: modal.$edge-border-radius;
          border-bottom-right-radius: modal.$edge-border-radius;
        }
      }
    }

    .start-date-suggestions,
    .version {
      grid-column-start: 2;
      margin-top: -0.3em;
    }
  }
</style>
