<script context="module" lang="ts">
  export enum View {
    Installed,
    FilterInstalled,
    Search,
    Reconcile,
  }
</script>

<script lang="ts">
  import type Api from "../api";
  import lodash from "lodash";
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";
  import Addon from "./Addon.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";

  export let api: Api, isActive: boolean, profile: string;

  const debounceDelay = 500;
  const searchLimit = 25;

  let sources: object;
  let protocols: string[];
  let activeView: View = View.Installed;
  let addons: any[];
  let addonUpdates: number;
  let installedAddons = [];
  let searchAddons = [];
  let searchTerms = "";
  let searchesInProgress = 0;
  let refreshInProgress = false;
  let selected = [];
  let toInstall = [];
  let toUpdate = [];
  let toRemove = [];

  const matchCmp = ([installedAddon], [otherAddon]) =>
    installedAddon.source === otherAddon.source && installedAddon.id === otherAddon.id;

  const installOrUpdate = async (
    method: "install" | "update",
    defns: { source: string; name: string }[],
    extraParams: object = {}
  ) => {
    const result = await api.modifyAddons("install", defns, extraParams);
    const defnResultPairs = lodash.zip(defns, result);
    const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);
    if (resultGroups.success) {
      const justInstalledAddons = resultGroups.success.map(([, [, addon]]) => addon);
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
  };

  const install = async (defns: { source: string; name: string }[], replace = false) => {
    await installOrUpdate("install", defns, { replace: replace });
  };

  const update = async (defns: { source: string; name: string }[]) => {
    await installOrUpdate("update", defns);
  };

  const remove = async (defns: { source: string; name: string }[]) => {
    const result = await api.modifyAddons("remove", defns);
    const defnResultPairs = lodash.zip(defns, result);
    const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);
    if (resultGroups.success) {
      const removedAddons = resultGroups.success.map(([, [, addon]]) => addon);
      installedAddons = lodash.differenceWith(installedAddons, removedAddons, matchCmp);
      const removedAddonsInSearch = lodash.intersectionWith(removedAddons, searchAddons, matchCmp);
      searchAddons = lodash.unionWith(removedAddonsInSearch, searchAddons, matchCmp);
    }

    for (const [defn, [, message]] of Array.prototype.concat(
      resultGroups.failure || [],
      resultGroups.error || []
    )) {
      alert(`Failed to remove ${defn.source}:${defn.name}: ${message}`);
    }
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

  const select = (addon) => {
    selected = lodash.xorWith(selected, [addon], lodash.isEqual);
  };

  const refresh = async () => {
    if (!refreshInProgress) {
      refreshInProgress = true;
      try {
        installedAddons = await api.listAddons(true);
      } finally {
        refreshInProgress = false;
      }
    }
  };

  const setupComponent = async () => {
    if (!refreshInProgress) {
      refreshInProgress = true;
      try {
        sources = await api.listSources();
        protocols = [...Object.keys(sources), "http", "https"].map((v) => `${v}:`);
        for (const checkForUpdates of [false, true]) {
          installedAddons = await api.listAddons(checkForUpdates);
        }
        addonUpdates = installedAddons.reduce(
          (val, [, { new_version }]) => val + (new_version ? 1 : 0),
          0
        );
      } finally {
        refreshInProgress = false;
      }
    }
  };

  const reconcile = async (matcher: "toc_ids" | "dir_names" | "toc_names") => {
    const results = await api.reconcile(matcher);
    console.log(results);
    return results;
  };

  onMount(setupComponent);

  // Update list view - we're restoring installed add-ons immediately but debouncing searches
  $: searchTerms ? search() : (activeView = View.Installed);
  $: switch (activeView) {
    case View.Search:
      addons = searchAddons;
      break;
    case View.Reconcile:
      addons = [];
      break;
    default:
      addons = installedAddons;
  }
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
    {addonUpdates}
    {searchesInProgress}
    {refreshInProgress}
    {refresh} />
  <div class="addon-list-wrapper">
    {#if activeView === View.Reconcile}
      {#await reconcile('toc_ids')}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then [reconciled, unreconciled]}
        {#if reconciled.length || unreconciled.length}
          <ul class="addon-list">
            {#each reconciled as [folders, choices], idx}
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
        {#each addons as [addon, addonMeta] (`${addon.source}:${addon.id}`)}
          <Addon
            on:requestSelect={(event) => select(event.detail)}
            on:requestInstall={(event) => install([event.detail])}
            on:requestUpdate={(event) => update([event.detail])}
            on:requestRemove={(event) => remove([event.detail])}
            {addon}
            {addonMeta}
            {sources}
            {refreshInProgress} />
        {/each}
      </ul>
    {/if}
  </div>
{/if}