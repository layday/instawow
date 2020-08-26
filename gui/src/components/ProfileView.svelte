<script context="module" lang="ts">
  export enum View {
    Installed,
    FilterInstalled,
    Search,
    Reconcile,
  }
</script>

<script lang="ts">
  import type { Addon, AddonMeta, Api, ListResult, Sources } from "../api";
  import lodash from "lodash";
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";
  import AddonComponent from "./Addon.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";

  export let api: Api, isActive: boolean;

  const debounceDelay = 500;
  const searchLimit = 25;

  let sources: Sources;
  let protocols: string[];
  let activeView: View = View.Installed;
  let addons: ListResult;
  let installedAddons: ListResult = [];
  let searchAddons: ListResult = [];
  let addonsBeingModified: string[] = [];
  let addonUpdates: number;
  let searchTerms = "";
  let searchesInProgress = 0;
  let refreshInProgress = false;
  let reconciliationStage;

  const sleep = (ms: number) => {
    return new Promise((resolve) => setTimeout(resolve, ms));
  };

  const matchCmp = ([installedAddon]: [Addon, AddonMeta], [otherAddon]: [Addon, AddonMeta]) =>
    installedAddon.source === otherAddon.source && installedAddon.id === otherAddon.id;

  const attachId = ([addon, addonMeta]): [Addon, AddonMeta, string] => {
    const id = `${addon.source}:${addon.id}`;
    return [addon, addonMeta, id];
  };

  const countUpdates = () =>
    (addonUpdates = installedAddons.reduce(
      (val, [, { new_version }]) => val + (new_version ? 1 : 0),
      0
    ));

  const installOrUpdate = async (
    method: "install" | "update",
    defns: { source: string; name: string }[],
    extraParams: object = {}
  ) => {
    const ids = defns.map(({ source, name }) => `${source}:${name}`);
    addonsBeingModified = [...addonsBeingModified, ...ids];

    try {
      const result = await api.modifyAddons(method, defns, extraParams);
      const defnResultPairs = lodash.zip(defns, result);
      const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);
      if (resultGroups.success) {
        const justInstalledAddons = resultGroups.success.map(([, [, addon]]) => addon) as [
          Addon,
          AddonMeta
        ][];
        installedAddons = lodash.unionWith(justInstalledAddons, installedAddons, matchCmp);
        // We've got to go about the intersection in a slightly roundabout way
        // for search cuz lodash extracts the match from the first array
        const justInstalledAddonsInSearch = lodash.intersectionWith(
          justInstalledAddons,
          searchAddons,
          matchCmp
        );
        searchAddons = lodash.unionWith(justInstalledAddonsInSearch, searchAddons, matchCmp);
      }

      for (const [defn, [, message]] of Array.prototype.concat(
        resultGroups.failure || [],
        resultGroups.error || []
      )) {
        alert(`Failed to ${method} ${defn.source}:${defn.name}: ${message}`);
      }
    } finally {
      addonsBeingModified = lodash.xor(addonsBeingModified, ids);
    }
  };

  const install = async (defns: { source: string; name: string }[], replace = false) => {
    await installOrUpdate("install", defns, { replace: replace });
  };

  const update = async (defns: { source: string; name: string }[]) => {
    await installOrUpdate("update", defns);
    countUpdates();
  };

  const updateAll = async () => {
    const outdatedAddons = installedAddons.filter(([, { new_version }]) => new_version);
    const defns = outdatedAddons.map(([{ source, id }]) => ({ source: source, name: id }));
    await update(defns);
  };

  const remove = async (defns: { source: string; name: string }[]) => {
    const ids = defns.map(({ source, name }) => `${source}:${name}`);
    addonsBeingModified = [...addonsBeingModified, ...ids];

    try {
      const result = await api.modifyAddons("remove", defns);
      const defnResultPairs = lodash.zip(defns, result);
      const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);
      if (resultGroups.success) {
        const removedAddons = resultGroups.success.map(([, [, addon]]) => addon) as [
          Addon,
          AddonMeta
        ][];
        installedAddons = lodash.differenceWith(installedAddons, removedAddons, matchCmp);
        const removedAddonsInSearch = lodash.intersectionWith(
          removedAddons,
          searchAddons,
          matchCmp
        );
        searchAddons = lodash.unionWith(removedAddonsInSearch, searchAddons, matchCmp);
      }

      for (const [defn, [, message]] of Array.prototype.concat(
        resultGroups.failure || [],
        resultGroups.error || []
      )) {
        alert(`Failed to remove ${defn.source}:${defn.name}: ${message}`);
      }
    } finally {
      addonsBeingModified = lodash.xor(addonsBeingModified, ids);
    }
  };

  const reconcile = async (matcher: "toc_ids" | "dir_names" | "toc_names") => {
    const results = await api.reconcile(matcher);
    console.log(results);
    return results;
  };

  const search = lodash.debounce(async () => {
    searchesInProgress++;
    try {
      const searchTermsSnapshot = searchTerms;
      if (searchTermsSnapshot) {
        let maybeUrl: URL;
        try {
          maybeUrl = new URL(searchTermsSnapshot);
        } catch {
          //
        }
        const results = await (maybeUrl && protocols.includes(maybeUrl.protocol)
          ? api.resolveUris([searchTermsSnapshot])
          : api.searchForAddons(searchTermsSnapshot, searchLimit));
        if (searchTermsSnapshot === searchTerms) {
          const resultsInInstalledAddons = lodash.intersectionWith(
            installedAddons,
            results,
            matchCmp
          );
          const combinedAddons = lodash.unionWith(resultsInInstalledAddons, results, matchCmp);
          searchAddons = combinedAddons;
          activeView = View.Search;
        }
      }
    } finally {
      searchesInProgress--;
    }
  }, debounceDelay);

  const refresh = async () => {
    if (!refreshInProgress) {
      refreshInProgress = true;
      try {
        installedAddons = await api.listAddons(true);
        countUpdates();
      } finally {
        refreshInProgress = false;
      }
    }
  };

  const setupComponent = async () => {
    refreshInProgress = true;
    try {
      sources = await api.listSources();
      protocols = [...Object.keys(sources), "http", "https"].map((v) => `${v}:`);
      for (const checkForUpdates of [false, true]) {
        installedAddons = await api.listAddons(checkForUpdates);
      }
      countUpdates();
    } finally {
      refreshInProgress = false;
    }
  };

  onMount(setupComponent);

  // Update list view - we're restoring installed add-ons immediately but debouncing searches
  $: searchTerms ? search() : (activeView = View.Installed);
  $: activeView === View.Search ? (addons = searchAddons) : (addons = installedAddons);
</script>

<style lang="scss">
  @import "vars";

  .placeholder {
    display: flex;
    flex-grow: 1;
    place-items: center;

    div {
      flex-grow: 1;
      text-align: center;
    }
  }

  .addon-list-wrapper {
    @include stretch-vertically;
    height: 100%;
    overflow-y: auto;
    padding: 0.5em 0;
    border-radius: 6px;
    border: 1px solid var(--inverse-color-10);
    -webkit-user-select: none;
  }

  .addon-list {
    @include unstyle-list;
  }
</style>

{#if isActive}
  <AddonListNav
    bind:activeView
    bind:searchTerms
    on:requestRefresh={() => refresh()}
    on:requestUpdateAll={() => updateAll()}
    {addonUpdates}
    refreshing={refreshInProgress}
    searching={searchesInProgress > 0} />
  <div class="addon-list-wrapper">
    {#if activeView === View.Reconcile}
      {#await reconcile('dir_names')}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then [reconciled, unreconciled]}
        {#if reconciled.length || unreconciled.length}
          <ul class="addon-list">
            {#each Array.prototype.concat( reconciled, lodash
                .sortBy(unreconciled, (f) => f.name)
                .map((f) => [[f], []]) ) as [folders, choices], idx}
              <AddonStub {folders} {choices} {idx} />
            {/each}
          </ul>
        {:else}
          <div class="placeholder" in:fade>
            <div>Reconciliation complete.</div>
          </div>
        {/if}
      {/await}
    {:else}
      <ul class="addon-list">
        {#each addons.map(attachId) as [addon, addonMeta, id] (id)}
          <AddonComponent
            on:requestInstall={(event) => install([event.detail])}
            on:requestUpdate={(event) => update([event.detail])}
            on:requestRemove={(event) => remove([event.detail])}
            {addon}
            {addonMeta}
            {sources}
            beingModified={addonsBeingModified.includes(id)}
            refreshing={refreshInProgress} />
        {/each}
      </ul>
    {/if}
  </div>
{/if}
