<script context="module" lang="ts">
  export const addonToDefn = (addon: Addon) => ({ source: addon.source, name: addon.id });

  const attachDefntoAddon = ([addon, addonMeta]): [Addon, AddonMeta, Defn] => [
    addon,
    addonMeta,
    addonToDefn(addon),
  ];

  type CreateTokenSignature = {
    (addon: Addon): string;
    (defn: Defn): string;
  };

  const createToken: CreateTokenSignature = (value: any) =>
    [value.source, value.id || value.name].join(":");

  const matchCmp = ([thisAddon]: [Addon, AddonMeta], [otherAddon]: [Addon, AddonMeta]) =>
    thisAddon.source === otherAddon.source && thisAddon.id === otherAddon.id;

  const debounceDelay = 500;
  const searchLimit = 25;
</script>

<script lang="ts">
  import type { Addon, AddonMeta, Api, Defn, ListResult, ModifyResult, Sources } from "../api";
  import { View } from "../constants";
  import { profiles } from "../store";
  import { ipcRenderer } from "electron";
  import lodash from "lodash";
  import { onMount } from "svelte";
  import { flip } from "svelte/animate";
  import { fade } from "svelte/transition";
  import AddonComponent from "./Addon.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import InstallationModal from "./InstallationModal.svelte";
  import RollbackModal from "./RollbackModal.svelte";

  export let profile: string, api: Api, isActive: boolean;

  let sources: Sources;
  let protocols: string[];

  let activeView: View = View.Installed;
  let addons__Installed: ListResult;
  let addons__Search: ListResult;
  let addons__CombinedSearch: ListResult;
  let outdatedAddons: number;
  let searchTerms: string = "";
  let refreshInProgress: boolean = false;
  let searchesInProgress: number = 0;

  let notifications;

  let addonsBeingModified: string[] = [];   // revisit

  let modalToShow: "install" | "reinstall" | "rollback" | false = false;
  let modalProps: object;

  let reconciliationStage;
  let reconciliationSelections;

  const countUpdates = () =>
    (outdatedAddons = addons__Installed.reduce(
      (val, [, { new_version }]) => val + (new_version ? 1 : 0),
      0
    ));

  const regenerateCombinedSearchAddons = () => {
    const installedAddonsInSearch = lodash.intersectionWith(
      addons__Installed,
      addons__Search,
      matchCmp
    );
    addons__CombinedSearch = lodash.unionWith(installedAddonsInSearch, addons__Search, matchCmp);
  };

  const notifyOfFailures = (
    method: "install" | "update" | "remove",
    resultGroups: { [kind: string]: ModifyResult }
  ) => {
    for (const [defn, [, message]] of Array.prototype.concat(
      resultGroups.failure || [],
      resultGroups.error || []
    )) {
      alert(`failed to ${method} ${createToken(defn)}: ${message}`);
    }
  };

  const modify = async (
    method: "install" | "update" | "remove",
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
        const modifiedAddons = resultGroups.success.map(([, [, addon]]) => addon) as [
          Addon,
          AddonMeta
        ][];
        if (method === "remove") {
          addons__Installed = lodash.differenceWith(addons__Installed, modifiedAddons, matchCmp);
        } else {
          addons__Installed = lodash.unionWith(modifiedAddons, addons__Installed, matchCmp);
        }
        regenerateCombinedSearchAddons();
      }

      notifyOfFailures(method, resultGroups as any);
    } finally {
      addonsBeingModified = lodash.difference(addonsBeingModified, ids);
    }
  };

  const install = async (defns: Defn[], replace = false) => {
    await modify("install", defns, { replace: replace });
  };

  type UpdateSignature = {
    (defns: Defn[]): Promise<void>;
    (all: true): Promise<void>;
  };

  const update: UpdateSignature = async (value: any) => {
    if (value === true) {
      const outdatedAddons = addons__Installed.filter(([, { new_version }]) => new_version);
      const defns = outdatedAddons.map(([addon]) => addonToDefn(addon));
      await modify("update", defns);
    } else {
      await modify("update", value);
    }
  };

  const remove = async (defns: Defn[]) => {
    await modify("remove", defns);
  };

  // TODO: implement in the server w/ transactions
  const reinstall = async (defns: Defn[]) => {
    await remove(defns);
    await install(defns);
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
          addons__Search = results;
          regenerateCombinedSearchAddons();
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
        addons__Installed = await api.listAddons(true);
      } finally {
        refreshInProgress = false;
      }
    }
  };

  const showModal = ([modal, defn, versions]: [
    "install" | "reinstall" | "rollback",
    Defn,
    Addon["logged_versions"]?
  ]) => {
    if (modal === "install" || modal === "reinstall") {
      modalProps = { defn: defn, source: sources[defn.source] };
    } else if (modal === "rollback") {
      modalProps = { defn: defn, versions: versions };
    }
    modalToShow = modal;
  };

  const revealFolder = (folder: string) =>
    ipcRenderer.send("reveal-addon-folder", [$profiles[profile].addon_dir, folder]);

  const setupComponent = async () => {
    refreshInProgress = true;
    try {
      sources = await api.listSources();
      protocols = [...Object.keys(sources), "http", "https"].map((v) => `${v}:`);
      for (const checkForUpdates of [false, true]) {
        addons__Installed = await api.listAddons(checkForUpdates);
      }
      if (!addons__Installed.length) {
        activeView = View.Reconcile;
      }
    } finally {
      refreshInProgress = false;
    }
  };

  onMount(setupComponent);

  // Update list view - we're restoring installed add-ons immediately but debouncing searches
  $: searchTerms ? search() : (activeView = View.Installed);
  $: addons = (activeView === View.Search ? addons__CombinedSearch : addons__Installed) ?? [];
  $: addons__Installed && countUpdates();
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

    :nth-child(odd) {
      background-color: var(--inverse-color-05);
    }
  }
</style>

{#if isActive}
  <AddonListNav
    on:requestRefresh={() => refresh()}
    on:requestUpdateAll={() => update(true)}
    bind:activeView
    bind:searchTerms
    {outdatedAddons}
    refreshing={refreshInProgress}
    searching={searchesInProgress > 0} />
  <div class="addon-list-wrapper" class:prevent-scrolling={!!modalToShow}>
    {#if modalToShow === 'install' || modalToShow === 'reinstall'}
      <InstallationModal
        on:requestInstall={(event) => install([event.detail])}
        on:requestReinstall={(event) => reinstall([event.detail])}
        bind:show={modalToShow}
        {...modalProps} />
    {:else if modalToShow === 'rollback'}
      <RollbackModal
        on:requestReinstall={(event) => reinstall([event.detail])}
        bind:show={modalToShow}
        {...modalProps} />
    {/if}
    {#if activeView === View.Reconcile}
      <!--  -->
      {#await reconcile('dir_names')}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then [reconciled, unreconciled]}
        {#if reconciled.length || unreconciled.length}
          <ul class="addon-list">
            {#each Array.prototype.concat( reconciled, lodash.map((f) => [
                [f],
                [],
              ]) ) as [folders, choices], idx}
              <li>
                <AddonStub {folders} {choices} {idx} />
              </li>
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
        {#each addons.map(attachDefntoAddon) as [addon, addonMeta, defn] (createToken(defn))}
          <li animate:flip={{ duration: 200 }}>
            <AddonComponent
              on:requestInstall={(e) => install([e.detail])}
              on:requestUpdate={(e) => update([e.detail])}
              on:requestRemove={(e) => remove([e.detail])}
              on:requestReinstall={(e) => reinstall([e.detail])}
              on:requestShowModal={(e) => showModal(e.detail)}
              on:requestShowModal={(e) => showModal(e.detail)}
              on:requestRevealFolder={(e) => revealFolder(e.detail)}
              {addon}
              {addonMeta}
              {sources}
              beingModified={addonsBeingModified.includes(createToken(defn))}
              refreshing={refreshInProgress} />
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
