<script lang="ts">
  import { getContext } from "svelte";
  import type { Sources } from "../api";
  import { Strategy } from "../api";
  import type { SearchOptions } from "./Profile.svelte";
  import type { ModalHandle } from "./modal/Modal.svelte";

  let {
    sources,
    searchFilterInstalled,
    searchIsFromAlias,
    searchOptions = $bindable(),
    onRequestReset,
    onRequestSearch,
  }: {
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
  }

  .form-control.checkbox-container {
    background-color: transparent;
    padding-left: 0;
  }
</style>
