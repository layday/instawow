<script lang="ts">
  import type { Sources } from "../api";
  import { Flavour, Strategy } from "../api";
  import { createEventDispatcher } from "svelte";
  import { fly, scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: boolean,
    sources: Sources,
    flavour: Flavour,
    searchSources: string[],
    searchFromAlias: boolean,
    searchCutoffDate: string | null,
    searchStrategy: Strategy,
    searchVersion: string;

  const cutoffDateSuggestions = [
    { date: "2021-11-02", patch: "9.1.5", flavour: Flavour.retail },
    { date: "2020-10-13", patch: "9.0.1", flavour: Flavour.retail },
  ];

  const dispatch = createEventDispatcher();

  const requestSearch = () => {
    dispatch("requestSearch");
    show = false;
  };
</script>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <form class="content" on:submit|preventDefault={() => requestSearch()}>
      <label for="__search-source">sources:</label>
      <select id="__search-source" multiple disabled={searchFromAlias} bind:value={searchSources}>
        {#each Object.values(sources) as { source, name }}
          <option value={source}>{name}</option>
        {/each}
      </select>
      <label for="__search-cutoff-date">cut-off date:</label>
      <input
        type="text"
        id="__search-cutoff-date"
        placeholder="YYYY-MM-DD"
        disabled={searchFromAlias}
        bind:value={searchCutoffDate}
      />
      <ul class="cutoff-date-suggestions">
        {#each cutoffDateSuggestions as { date, patch, flavour: suggestionFlavour }}
          {#if flavour === suggestionFlavour}
            <li on:click={() => (searchCutoffDate = date)}>{patch}</li>
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
      <button type="submit">search</button>
    </form>
  </dialog>
</Modal>

<style lang="scss">
  @import "scss/modal";
  @import "scss/vars";

  form {
    display: grid;
    grid-template-columns: 1fr 2fr;
    column-gap: 0.5rem;
    row-gap: 0.5rem;

    button {
      grid-column-start: span 2;
    }

    label {
      line-height: $form-el-line-height;
      color: var(--inverse-color-tone-10);
      text-align: right;
    }

    .version {
      grid-column-start: 2;
    }

    .cutoff-date-suggestions {
      @include unstyle-list;
      grid-column-start: 2;
      display: inline-flex;
      gap: 0.2rem;
      font-size: 0.8em;
      font-weight: 600;

      li {
        cursor: pointer;
        padding: 0.2rem 0.4rem;
        border-radius: $edge-border-radius;
        background-color: var(--inverse-color-tone-20);
        color: var(--base-color);
      }
    }
  }
</style>
