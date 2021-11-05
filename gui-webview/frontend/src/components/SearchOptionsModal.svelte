<script lang="ts">
  import type { Sources } from "../api";
  import { Strategy } from "../api";
  import { createEventDispatcher } from "svelte";
  import { fly, scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any,
    sources: Sources,
    search__sources: string[],
    search__cutoffDate: string | null,
    search__strategy: Strategy,
    search__version: string;

  const dispatch = createEventDispatcher();

  const requestSearch = () => {
    dispatch("requestSearch");
    show = false;
  };
</script>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <form class="content" on:submit|preventDefault={() => requestSearch()}>
      <label for="__search-source">source</label>
      <select class="row" id="__search-source" multiple bind:value={search__sources}>
        {#each Object.values(sources) as { source, name }}
          <option value={source}>{name}</option>
        {/each}
      </select>
      <label for="__search-strategy">strategy</label>
      <select class="row" id="__search-strategy" bind:value={search__strategy}>
        {#each Object.values(Strategy) as strategy}
          <option value={strategy}>{strategy}</option>
        {/each}
      </select>
      {#if search__strategy === Strategy.version}
        <input
          type="text"
          class="row version"
          placeholder="version"
          aria-label="version"
          bind:value={search__version}
          in:fly={{ duration: 200, y: -64 }}
        />
      {/if}
      <label for="__search-cutoff-date">cut-off date</label>
      <input
        type="text"
        class="row"
        id="__search-cutoff-date"
        placeholder="YYYY-MM-DD"
        bind:value={search__cutoffDate}
      />
      <button class="row" type="submit">apply</button>
    </form>
  </dialog>
</Modal>

<style lang="scss">
  @import "scss/modal";

  label {
    display: block;
    margin-bottom: 0.1em;
    padding: 0 0.5em;
    color: var(--inverse-color-tone-20);

    &:not(:first-child) {
      margin-top: 0.5em;
    }
  }
</style>
