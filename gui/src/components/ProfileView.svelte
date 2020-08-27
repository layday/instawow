<script context="module" lang="ts">
  export enum View {
    Installed,
    FilterInstalled,
    Search,
    Reconcile,
  }
</script>

<script lang="ts">
  import type { Addon, AddonMeta, Api, Defn, ListResult, ModifyResult, Sources } from "../api";
  import { ipcRenderer } from "electron";
  import lodash from "lodash";
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";
  import AddonComponent from "./Addon.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import InstallationModal from "./InstallationModal.svelte";

  export let profile: string, api: Api, isActive: boolean;

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
  let showInstallationModal = false;
  let installationModalProps;

  const matchCmp = ([installedAddon]: [Addon, AddonMeta], [otherAddon]: [Addon, AddonMeta]) =>
    installedAddon.source === otherAddon.source && installedAddon.id === otherAddon.id;

  type CreateTokenSignature = {
    (addon: Addon): string;
    (defn: Defn): string;
  };

  const createToken: CreateTokenSignature = (value: any) =>
    [value.source, value.id || value.name].join(":");

  const attachTokentoAddon = ([addon, addonMeta]): [Addon, AddonMeta, string] => [
    addon,
    addonMeta,
    createToken(addon),
  ];

  const countUpdates = () =>
    (addonUpdates = installedAddons.reduce(
      (val, [, { new_version }]) => val + (new_version ? 1 : 0),
      0
    ));

  const notifyOfFailures = (
    method: "install" | "update" | "remove",
    resultGroups: { [kind: string]: ModifyResult }
  ) => {
    for (const [defn, [, message]] of Array.prototype.concat(
      resultGroups.failure || [],
      resultGroups.error || []
    )) {
      alert(`Failed to ${method} ${createToken(defn)}: ${message}`);
    }
  };

  const installOrUpdate = async (
    method: "install" | "update",
    defns: Defn[],
    extraParams: object = {}
  ) => {
    const ids = defns.map(createToken);
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

      notifyOfFailures(method, resultGroups as any);
    } finally {
      addonsBeingModified = lodash.difference(addonsBeingModified, ids);
    }
  };

  const install = async (defns: Defn[], replace = false) => {
    await installOrUpdate("install", defns, { replace: replace });
  };

  type UpdateSignature = {
    (defns: Defn[]): Promise<void>;
    (all: true): Promise<void>;
  };

  const update: UpdateSignature = async (value: any) => {
    if (value === true) {
      const outdatedAddons = installedAddons.filter(([, { new_version }]) => new_version);
      const defns = outdatedAddons.map(([{ source, id }]) => ({ source: source, name: id }));
      await installOrUpdate("update", defns);
    } else {
      await installOrUpdate("update", value);
    }
    countUpdates();
  };

  const remove = async (defns: Defn[]) => {
    const ids = defns.map(createToken);
    addonsBeingModified = [...addonsBeingModified, ...ids];

    try {
      const method = "remove";
      const result = await api.modifyAddons(method, defns);
      const defnResultPairs = lodash.zip(defns, result);
      const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);

      if (resultGroups.success) {
        const removedAddons = resultGroups.success.map(([, [, addon]]) => addon) as [
          Addon,
          AddonMeta
        ][];
        // TODO: replace removed add-ons with original add-ons
        installedAddons = lodash.differenceWith(installedAddons, removedAddons, matchCmp);
        const removedAddonsInSearch = lodash.intersectionWith(
          removedAddons,
          searchAddons,
          matchCmp
        );
        searchAddons = lodash.unionWith(removedAddonsInSearch, searchAddons, matchCmp);
      }

      notifyOfFailures(method, resultGroups as any);
    } finally {
      addonsBeingModified = lodash.difference(addonsBeingModified, ids);
    }
  };

  const reinstall = async (defns: Defn[]) => {
    const ids = defns.map(createToken);
    addonsBeingModified = [...addonsBeingModified, ...ids];

    let toReinstall: Defn[];
    try {
      const method = "remove";
      const result = await api.modifyAddons(method, defns);
      const defnResultPairs = lodash.zip(defns, result);
      const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);
      toReinstall = resultGroups.success.map(([defn]) => defn);
      notifyOfFailures(method, resultGroups as any);
    } catch (error) {
      addonsBeingModified = lodash.difference(addonsBeingModified, ids);
      throw error;
    }

    try {
      // TODO: handled failed installs
      await install(toReinstall);
      countUpdates();
    } finally {
      addonsBeingModified = lodash.difference(addonsBeingModified, ids);
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

  const showModal = (defn: Defn) => {
    const source = sources[defn.source];
    installationModalProps = { source: source, defn: defn };
    showInstallationModal = true;
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
    position: relative;
    height: 100%;
    overflow-y: auto;
    padding: 0.5em 0;
    border-radius: 6px;
    border: 1px solid var(--inverse-color-10);
    -webkit-user-select: none;

    &.prevent-scrolling {
      overflow-y: hidden;
    }
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
    on:requestUpdateAll={() => update(true)}
    {addonUpdates}
    refreshing={refreshInProgress}
    searching={searchesInProgress > 0} />
  <div class="addon-list-wrapper" class:prevent-scrolling={showInstallationModal}>
    {#if showInstallationModal}
      <InstallationModal
        on:requestInstall={(event) => install([event.detail])}
        on:requestReinstall={(event) => reinstall([event.detail])}
        bind:show={showInstallationModal}
        {...installationModalProps} />
    {/if}
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
        {#each addons.map(attachTokentoAddon) as [addon, addonMeta, token] (token)}
          <AddonComponent
            on:requestInstall={(event) => install([event.detail])}
            on:requestUpdate={(event) => update([event.detail])}
            on:requestRemove={(event) => remove([event.detail])}
            on:requestReinstall={(event) => reinstall([event.detail])}
            on:requestShowModal={(event) => showModal(event.detail)}
            {addon}
            {addonMeta}
            {sources}
            beingModified={addonsBeingModified.includes(token)}
            refreshing={refreshInProgress} />
        {/each}
      </ul>
    {/if}
  </div>
{/if}
