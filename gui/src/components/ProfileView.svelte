<script context="module" lang="ts">
  import { ReconciliationStage, View } from "../constants";

  export const addonToDefn = (addon: Addon) => ({ source: addon.source, name: addon.id });

  type CreateTokenSignature = {
    (addon: Addon): string;
    (defn: Defn): string;
  };

  const createToken: CreateTokenSignature = (value: any) =>
    [value.source, value.id || value.name].join(":");

  const matchCmp = ([thisAddon]: [Addon, AddonMeta], [otherAddon]: [Addon, AddonMeta]) =>
    thisAddon.source === otherAddon.source && thisAddon.id === otherAddon.id;

  const attachTokentoAddon = ([addon, addonMeta]): [Addon, AddonMeta, string] => [
    addon,
    addonMeta,
    createToken(addon),
  ];

  const reconciliationStages = Object.values(ReconciliationStage);

  const getReconcilePrevStage = (stage: ReconciliationStage) =>
    reconciliationStages[reconciliationStages.indexOf(stage) - 1];

  const getReconcileNextStage = (stage: ReconciliationStage) =>
    reconciliationStages[reconciliationStages.indexOf(stage) + 1];

  const debounceDelay = 500;
  const searchLimit = 25;
</script>

<script lang="ts">
  import type { Addon, AddonMeta, Api, Defn, ListResult, ModifyResult, Sources } from "../api";
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
  let outdatedAddonCount: number;
  let searchTerms: string = "";

  let reconciliationStage: ReconciliationStage = reconciliationStages[0];
  let reconciliationSelections: Addon[];

  let refreshInProgress: boolean = false;
  let searchesInProgress: number = 0;
  let reconciliationInstallationInProgress: boolean = false;

  let modalToShow: "install" | "reinstall" | "rollback" | false = false;
  let modalProps: object;

  let notifications;

  let addonsBeingModified: string[] = []; // revisit

  const countUpdates = () =>
    (outdatedAddonCount = addons__Installed.reduce(
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
      const outdatedAddonCount = addons__Installed.filter(([, { new_version }]) => new_version);
      const defns = outdatedAddonCount.map(([addon]) => addonToDefn(addon));
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

  const reconcile = async (thisStage: ReconciliationStage) => {
    reconciliationSelections = [];
    const stages = reconciliationStages.slice(reconciliationStages.indexOf(thisStage));
    for (const stage of stages) {
      console.debug("trying", stage);

      const results = await api.reconcile(stage);
      if (results.reconciled.length || !getReconcileNextStage(stage)) {
        reconciliationStage = stage;
        return results;
      }
    }
  };

  const installReconciled = async () => {
    reconciliationInstallationInProgress = true;
    try {
      await install(reconciliationSelections.filter(Boolean).map(addonToDefn), true);

      const nextStage = getReconcileNextStage(reconciliationStage);
      if (nextStage) {
        reconciliationStage = nextStage;
      }
    } finally {
      reconciliationInstallationInProgress = false;
    }
  };

  const search = async () => {
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
  };

  const searchDebounced = lodash.debounce(search, debounceDelay);

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

  const showAddonContextMenu = (addon: Addon) =>
    ipcRenderer.send("show-addon-context-menu", {
      pathComponents: [$profiles[profile].addon_dir, addon.folders[0].name],
      url: addon.url,
    });

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

  const setupComponent = async () => {
    refreshInProgress = true;
    try {
      sources = await api.listSources();
      protocols = [...Object.keys(sources), "http", "https"].map((v) => `${v}:`);
      // Grab the list of installed add-ons before checking for updates
      // which might take time
      for (const checkForUpdates of [false, true]) {
        addons__Installed = await api.listAddons(checkForUpdates);
      }
      // Immediately switch over to reconciliation if no add-ons are installed
      if (!addons__Installed.length) {
        activeView = View.Reconcile;
      }
    } finally {
      refreshInProgress = false;
    }
  };

  onMount(setupComponent);

  // Update list view - we're restoring installed add-ons immediately but debouncing searches
  $: searchTerms ? searchDebounced() : (activeView = View.Installed);
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

  .preamble {
    margin: 0;
    padding: 0.5rem;
    padding-top: 0;
    font-size: 0.9em;
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
    bind:activeView
    bind:searchTerms
    on:keydown={(e) => e.key === 'Enter' && search()}
    on:requestRefresh={() => refresh()}
    on:requestUpdateAll={() => update(true)}
    on:requestReconcileStepBackward={() => (reconciliationStage = getReconcilePrevStage(reconciliationStage))}
    on:requestReconcileStepForward={() => (reconciliationStage = getReconcileNextStage(reconciliationStage))}
    on:requestInstallReconciled={() => installReconciled()}
    on:requestAutomateReconciliation
    isSearching={searchesInProgress > 0}
    installed__isRefreshing={refreshInProgress}
    installed__outdatedAddonCount={outdatedAddonCount}
    reconciliation__isInstalling={reconciliationInstallationInProgress}
    reconciliation__canStepBackward={!!getReconcilePrevStage(reconciliationStage)}
    reconciliation__canStepForward={!!getReconcileNextStage(reconciliationStage)} />
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
      {#await reconcile(reconciliationStage)}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then result}
        {#if Object.values(result).some((v) => v.length)}
          <p class="preamble">
            Reconciliation is the process by which installed add-ons are linked with add-ons from
            sources. This is done in three stages in decreasing order of accuracy. Add-ons do not
            always carry source metadata and
            <i>instawow</i>
            employes a number of heuristics to reconcile add-ons which cannot be positively
            identified. If you trust
            <i>instawow</i>
            to do this without supervision, press "automate". Otherwise, review your selections
            below and press "install" to proceed to the next stage. Reconciled add-ons will be
            reinstalled.
          </p>
          <ul class="addon-list">
            {#each result.reconciled.concat(result.unreconciled) as { folders, matches: choices }, idx}
              <li>
                <AddonStub bind:selections={reconciliationSelections} {folders} {choices} {idx} />
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
        {#each addons.map(attachTokentoAddon) as [addon, addonMeta, token] (token)}
          <li animate:flip={{ duration: 200 }}>
            <AddonComponent
              on:requestInstall={(e) => install([e.detail])}
              on:requestUpdate={(e) => update([e.detail])}
              on:requestRemove={(e) => remove([e.detail])}
              on:requestReinstall={(e) => reinstall([e.detail])}
              on:requestShowModal={(e) => showModal(e.detail)}
              on:requestShowContexMenu={(e) => showAddonContextMenu(addon)}
              {addon}
              {addonMeta}
              {sources}
              beingModified={addonsBeingModified.includes(token)}
              refreshing={refreshInProgress} />
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
