<script context="module" lang="ts">
  import { ReconciliationStage, View } from "../constants";
  import { Strategies } from "../api";

  export const addonToDefn = (addon: Addon): Defn => ({
    source: addon.source,
    name: addon.id,
    strategy: addon.options.strategy as Strategies,
    ...(addon.options.strategy === "version" ? { strategy_vals: [addon.version] } : {}),
  });

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

  const reconcileStages = Object.values(ReconciliationStage);

  const getReconcilePrevStage = (stage: ReconciliationStage) =>
    reconcileStages[reconcileStages.indexOf(stage) - 1];

  const getReconcileNextStage = (stage: ReconciliationStage) =>
    reconcileStages[reconcileStages.indexOf(stage) + 1];

  const debounceDelay = 500;
  const searchLimit = 20;
</script>

<script lang="ts">
  import type { Addon, AddonMeta, Api, Defn, ListResult, ModifyResult, Sources } from "../api";
  import { profiles } from "../store";
  import { faQuestion } from "@fortawesome/free-solid-svg-icons";
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
  import Icon from "./SvgIcon.svelte";

  export let profile: string, api: Api, isActive: boolean;

  let sources: Sources;

  let activeView: View = View.Installed;
  let addons__Installed: ListResult;
  let addons__Search: ListResult;
  let addons__CombinedSearch: ListResult;
  let outdatedAddonCount: number;

  let searchTerms: string = "";
  let searchStrategy: Exclude<Strategies, "version"> = Strategies.default;

  let reconcileStage: ReconciliationStage = reconcileStages[0];
  let reconcileSelections: Addon[];

  let refreshInProgress: boolean = false;
  let searchesInProgress: number = 0;
  let reconcileInstallationInProgress: boolean = false;

  let modal: "install" | "reinstall" | "rollback" | false = false;
  let modalProps: object;

  let notifications; // TODO as a replacement for `notifyOfFailures`

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
    method: "install" | "update" | "remove" | "pin",
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
    method: "install" | "update" | "remove" | "pin",
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

  const pin = async (defns: Defn[]) => {
    await modify("pin", defns);
  };

  // TODO: implement in the server w/ transactions
  const reinstall = async (defns: Defn[]) => {
    await remove(defns);
    await install(defns);
  };

  const goToPrevReconcileStage = () => (reconcileStage = getReconcilePrevStage(reconcileStage));

  const goToNextReconcileStage = () => (reconcileStage = getReconcileNextStage(reconcileStage));

  const prepareReconcile = async (thisStage: ReconciliationStage) => {
    const stages = reconcileStages.slice(reconcileStages.indexOf(thisStage));
    for (const stage of stages) {
      console.debug("trying", stage);

      const results = await api.reconcile(stage);
      if (results.reconciled.length || !getReconcileNextStage(stage)) {
        reconcileStage = stage;
        reconcileSelections = [];
        return results;
      }
    }
  };

  const installReconciled = async (
    thisStage: ReconciliationStage,
    theseSelections: Addon[],
    recursive?: boolean
  ) => {
    reconcileInstallationInProgress = true;
    try {
      console.debug("installing selections from", thisStage);
      await install(theseSelections.filter(Boolean).map(addonToDefn), true);

      const nextStage = getReconcileNextStage(thisStage);
      if (nextStage) {
        if (recursive) {
          const { reconciled } = await api.reconcile(thisStage);
          const nextSelections = reconciled.map(({ matches: [addon] }) => addon);
          await installReconciled(nextStage, nextSelections, true);
        } else {
          reconcileStage = nextStage;
        }
      } else if (recursive) {
        // Trigger `prepareReconcile` to update the view when all is said and done
        reconcileStage = thisStage;
      }
    } finally {
      reconcileInstallationInProgress = false;
    }
  };

  const search = async () => {
    searchesInProgress++;
    try {
      const searchTermsSnapshot = searchTerms;
      if (searchTermsSnapshot) {
        const requests: [Promise<ListResult>, Promise<ListResult>] = [
          api.resolveUris([searchTermsSnapshot], searchStrategy),
          api.search(searchTermsSnapshot, searchLimit, searchStrategy),
        ];
        const results = lodash.unionWith(...(await Promise.all(requests)), matchCmp);
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

  const showModal = (thisModal: "install" | "reinstall" | "rollback", addon: Addon) => {
    const defn = addonToDefn(addon);
    if (thisModal === "install" || thisModal === "reinstall") {
      modalProps = { defn: defn, source: sources[defn.source] };
    } else if (thisModal === "rollback") {
      modalProps = { defn: defn, versions: addon.logged_versions };
    }
    modal = thisModal;
  };

  const showAddonContextMenu = async ([addon, addonMeta]: [Addon, AddonMeta]) => {
    const result = await ipcRenderer.invoke(
      "get-action-from-context-menu",
      [
        { action: "open-url", label: "Open in browser" },
        { action: "reveal-folder", label: "Reveal folder" },
        addonMeta.pinned ? { action: "unpin", label: "Unpin" } : { action: "pin", label: "Pin" },
        { action: "reinstall-with-strategy", label: "Reinstall" },
      ].filter(Boolean)
    );
    switch (result) {
      case "open-url":
        ipcRenderer.send("open-url", addon.url);
        break;
      case "reveal-folder":
        ipcRenderer.send("reveal-folder", [$profiles[profile].addon_dir, addon.folders[0].name]);
        break;
      case "pin":
      case "unpin":
        await pin([
          {
            ...addonToDefn(addon),
            strategy: result === "pin" ? Strategies.version : Strategies.default,
            strategy_vals: [addon.version],
          },
        ]);
        break;
      case "reinstall-with-strategy":
        showModal("reinstall", addon);
        break;
      default:
        break;
    }
  };

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
      // Keep actions disabled until after the addons have been reshuffled
      // to prevent misclicking
      setTimeout(() => (refreshInProgress = false), debounceDelay);
    }
  };

  onMount(setupComponent);

  // Update list view - we're restoring installed add-ons immediately but debouncing searches
  $: searchTerms && searchStrategy ? searchDebounced() : (activeView = View.Installed);
  // Reset the strategy in between searches
  $: searchTerms || (searchStrategy = Strategies.default);
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
    display: grid;
    grid-template-columns: 3rem 1fr;
    grid-column-gap: 0.5rem;
    align-items: center;
    margin: 0.25rem 0.75rem 0.75rem;
    padding: 0 0.75rem;
    font-size: 0.85em;
    border-radius: 4px;
    background-image: linear-gradient(45deg, rgba(pink, 0.2), rgba(orange, 0.2));
    color: var(--inverse-color-tone-10);

    :global(.icon) {
      width: 3rem;
      height: 3rem;
      fill: var(--inverse-color-tone-10);
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
    on:keydown={(e) => e.key === 'Enter' && search()}
    on:requestRefresh={() => refresh()}
    on:requestUpdateAll={() => update(true)}
    on:requestReconcileStepBackward={() => goToPrevReconcileStage()}
    on:requestReconcileStepForward={() => goToNextReconcileStage()}
    on:requestInstallReconciled={() => installReconciled(reconcileStage, reconcileSelections)}
    on:requestAutomateReconciliation={() => installReconciled(reconcileStage, reconcileSelections, true)}
    bind:activeView
    bind:search__searchTerms={searchTerms}
    bind:search__searchStrategy={searchStrategy}
    search__isSearching={searchesInProgress > 0}
    installed__isRefreshing={refreshInProgress}
    installed__outdatedAddonCount={outdatedAddonCount}
    reconcile__isInstalling={reconcileInstallationInProgress}
    reconcile__canStepBackward={!!getReconcilePrevStage(reconcileStage)}
    reconcile__canStepForward={!!getReconcileNextStage(reconcileStage)} />
  <div class="addon-list-wrapper" class:prevent-scrolling={!!modal}>
    {#if modal === 'install' || modal === 'reinstall'}
      <InstallationModal
        on:requestInstall={({ detail: [defn, replace] }) => install([defn], replace)}
        on:requestReinstall={({ detail: [defn] }) => reinstall([defn])}
        bind:show={modal}
        {...modalProps} />
    {:else if modal === 'rollback'}
      <RollbackModal
        on:requestReinstall={(event) => reinstall([event.detail])}
        bind:show={modal}
        {...modalProps} />
    {/if}
    {#if activeView === View.Reconcile}
      {#await prepareReconcile(reconcileStage)}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then result}
        {#if Object.values(result).some((v) => v.length)}
          <div class="preamble">
            <Icon icon={faQuestion} />
            <!-- prettier-ignore -->
            <p>
              Reconciliation is the process by which installed add-ons are linked with add-ons from
              sources. This is done in three stages in decreasing order of accuracy. Add-ons do not
              always carry source metadata and <i>instawow</i>
              employs a number of heuristics to reconcile add-ons which cannot be positively
              identified. If you trust <i>instawow</i>
              to do this without supervision, press "<b>automate</b>".
              Otherwise, review your selections below and press "<b>install</b>"
              to proceed to the next stage. Reconciled add-ons will be reinstalled.
            </p>
          </div>
          <ul class="addon-list">
            {#each result.reconciled.concat(result.unreconciled) as { folders, matches: choices }, idx}
              <li>
                <AddonStub bind:selections={reconcileSelections} {folders} {choices} {idx} />
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
              on:requestInstall={() => install([addonToDefn(addon)])}
              on:requestUpdate={() => update([addonToDefn(addon)])}
              on:requestRemove={() => remove([addonToDefn(addon)])}
              on:requestReinstall={() => reinstall([addonToDefn(addon)])}
              on:requestShowModal={(e) => showModal(e.detail, addon)}
              on:requestShowContexMenu={() => showAddonContextMenu([addon, addonMeta])}
              {addon}
              {addonMeta}
              canRollback={!!sources[addon.source]?.supports_rollback}
              beingModified={addonsBeingModified.includes(token)}
              refreshing={refreshInProgress} />
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
