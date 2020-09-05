<script context="module" lang="ts">
  import type { Addon, AddonWithMeta, Api, Defn, ListResult, ModifyResult, Sources } from "../api";
  import { Strategies, addonToDefn } from "../api";
  import { ReconciliationStage, View } from "../constants";
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
  import RollbackModal from "./RollbackModal.svelte";
  import Icon from "./SvgIcon.svelte";

  type ExtendedListResult = (readonly [AddonWithMeta, Addon?])[];

  type CreateTokenSignature = {
    (addon: Addon): string;
    (defn: Defn): string;
  };

  const createAddonToken: CreateTokenSignature = (value: Addon | Defn) =>
    [value.source, (value as Addon).id || (value as Defn).alias].join(":");

  const attachTokentoAddon = ([addon, otherAddon]: [AddonWithMeta, Addon]): [
    AddonWithMeta,
    Addon,
    string
  ] => [addon, otherAddon, createAddonToken(addon)];

  const cmpModifiedAddon = ([thisAddon]: readonly [AddonWithMeta, Addon?], otherAddon: Addon) =>
    thisAddon.source === otherAddon.source && thisAddon.id === otherAddon.id;

  const markAddonInstalled = (addon: Addon, installed = true): AddonWithMeta => ({
    __installed__: installed,
    ...addon,
  });

  const reconcileStages = Object.values(ReconciliationStage);

  const getReconcilePrevStage = (stage: ReconciliationStage) =>
    reconcileStages[reconcileStages.indexOf(stage) - 1];

  const getReconcileNextStage = (stage: ReconciliationStage) =>
    reconcileStages[reconcileStages.indexOf(stage) + 1];

  const defaultSearchState: {
    searchTerms: string;
    searchFromAlias: boolean;
    searchStrategy: Strategies;
    searchStrategyExtra: { [key: string]: any };
  } = {
    searchTerms: "",
    searchFromAlias: false,
    searchStrategy: Strategies.default,
    searchStrategyExtra: {},
  };
  const searchLimit = 20;
  const debounceDelay = 500;
</script>

<script lang="ts">
  export let profile: string, api: Api, isActive: boolean;

  let sources: Sources;

  let activeView: View = View.Installed;
  let addons__Installed: ExtendedListResult = [];
  let addons__Search: ListResult = [];
  let addons__CombinedSearch: ExtendedListResult = [];
  let outdatedAddonCount: number;
  let addonsBeingModified: string[] = []; // revisit

  let { searchTerms, searchFromAlias, searchStrategy, searchStrategyExtra } = defaultSearchState;

  let reconcileStage: ReconciliationStage = reconcileStages[0];
  let reconcileSelections: Addon[];

  let refreshInProgress: boolean = false;
  let searchesInProgress: number = 0;
  let reconcileInstallationInProgress: boolean = false;

  let modal: "rollback" | false = false;
  let modalProps: object;

  let addonsCondensed: boolean = false;
  let addonListEl: HTMLElement;

  const countUpdates = () =>
    (outdatedAddonCount = addons__Installed.reduce(
      (val, [thisAddon, otherAddon]) =>
        val + (otherAddon && thisAddon.version !== otherAddon.version ? 1 : 0),
      0
    ));

  const regenerateCombinedSearchAddons = () => {
    const combinedAddons = addons__Search.map((addon): [AddonWithMeta, Addon] => {
      const installedAddon = addons__Installed.find(
        ([installedAddon]) =>
          installedAddon.source === addon.source && installedAddon.id === addon.id
      );
      return [installedAddon?.[0] || markAddonInstalled(addon, false), addon];
    });
    addons__CombinedSearch = combinedAddons;
  };

  const notifyOfFailures = (
    method: "install" | "update" | "remove" | "pin",
    resultGroups: { [kind: string]: ModifyResult }
  ) => {
    for (const [defn, [, message]] of Array.prototype.concat(
      resultGroups.failure || [],
      resultGroups.error || []
    )) {
      alert(`failed to ${method} ${createAddonToken(defn)}: ${message}`);
    }
  };

  const modify = async (
    method: "install" | "update" | "remove" | "pin",
    defns: Defn[],
    extraParams: object = {}
  ) => {
    const ids = defns.map(createAddonToken);
    addonsBeingModified = [...addonsBeingModified, ...ids];

    try {
      const result = await api.modifyAddons(method, defns, extraParams);
      const defnResultPairs = lodash.zip(defns, result);
      const resultGroups = lodash.groupBy(defnResultPairs, ([, [status]]) => status);
      if (resultGroups.success) {
        const modifiedAddons = resultGroups.success.map(([, [, addon]]) => addon) as Addon[];
        if (method === "remove") {
          addons__Installed = lodash.differenceWith(
            addons__Installed,
            modifiedAddons,
            cmpModifiedAddon
          );
        } else {
          const installedAddons = [...addons__Installed];
          for (const addon of lodash.reverse(modifiedAddons)) {
            const newAddon = [markAddonInstalled(addon), addon] as const;
            const index = addons__Installed.findIndex((value) => cmpModifiedAddon(value, addon));
            if (index === -1) {
              installedAddons.unshift(newAddon);
            } else {
              installedAddons[index] = newAddon;
            }
          }
          addons__Installed = installedAddons;
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

  const update: UpdateSignature = async (value: Defn[] | true) => {
    if (value === true) {
      const outdatedAddons = addons__Installed.filter(
        ([{ version: thisVersion }, { version: otherVersion }]) => thisVersion !== otherVersion
      );
      const defns = outdatedAddons.map(([, addon]) => addonToDefn(addon));
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

  const search = async () => {
    searchesInProgress++;
    try {
      const searchTermsSnapshot = searchTerms;
      if (searchTermsSnapshot) {
        const coro = searchFromAlias
          ? api.resolve([
              {
                source: "*",
                alias: searchTermsSnapshot,
                strategy: { type_: searchStrategy, ...searchStrategyExtra },
              },
            ])
          : api.search(searchTermsSnapshot, searchLimit, searchStrategy);
        const results = await coro;
        // Discard the results if the search terms have changed in the interim
        if (searchTermsSnapshot === searchTerms) {
          addons__Search = results.filter(Boolean);
          regenerateCombinedSearchAddons();
          activeView = View.Search;
        }
      }
    } finally {
      searchesInProgress--;
    }
  };

  const searchDebounced = lodash.debounce(search, debounceDelay);

  const refreshInstalled = async (flash = false) => {
    if (!refreshInProgress) {
      refreshInProgress = true;
      try {
        const installedAddons = (await api.list()).map((addon) => markAddonInstalled(addon));
        if (flash) {
          addons__Installed = lodash.zip(installedAddons, installedAddons);
        }
        const resolvedAddons = await api.resolve(installedAddons.map(addonToDefn));
        addons__Installed = lodash.sortBy(
          lodash.zip(installedAddons, resolvedAddons),
          ([thisAddon, otherAddon]) => [thisAddon.version === otherAddon?.version, thisAddon.name]
        );
      } finally {
        // Keep actions disabled for a little while longer while the add-ons
        // are being reshuffled to prevent misclicking
        setTimeout(() => (refreshInProgress = false), debounceDelay);
      }
    }
  };

  const showModal = (thisModal: "rollback", addon: Addon) => {
    const defn = addonToDefn(addon);
    if (thisModal === "rollback") {
      modalProps = { defn: defn, versions: addon.logged_versions };
    }
    modal = thisModal;
  };

  const showGenericAddonContextMenu = async (addon: Addon) => {
    const selection = await ipcRenderer.invoke(
      "get-action-from-context-menu",
      [
        { action: "open-url", label: "Open in browser" },
        { action: "reveal-folder", label: "Reveal folder" },
        sources[addon.source]?.supports_rollback &&
          (addon.options.strategy === Strategies.version
            ? { action: "unpin", label: "Unpin" }
            : { action: "pin", label: "Pin" }),
        { action: "look-up", label: "Look up" },
      ].filter(Boolean)
    );
    switch (selection) {
      case "open-url":
        ipcRenderer.send("open-url", addon.url);
        break;
      case "reveal-folder":
        ipcRenderer.send("reveal-folder", [$profiles[profile].addon_dir, addon.folders[0].name]);
        break;
      case "pin":
      case "unpin":
        const defn = {
          ...addonToDefn(addon),
          ...{
            strategy:
              selection === "pin"
                ? { type_: Strategies.version, version: addon.version }
                : { type_: Strategies.default },
          },
        };
        await pin([defn]);
        break;
      case "look-up":
        searchFromAlias = true;
        searchStrategy = addon.options.strategy;
        searchStrategyExtra = { version: addon.version };
        // Modifying `searchTerms` last cuz we don't want to trigger repeat searches
        searchTerms = createAddonToken(addon);
        break;
      default:
        break;
    }
  };

  const showInstallAddonContextMenu = async (addon: Addon) => {
    const selection = await ipcRenderer.invoke("get-action-from-context-menu", [
      { action: "replace", label: "Replace existing" },
    ]);
    if (selection === "replace") {
      await install([addonToDefn(addon)], true);
    }
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
          const nextSelections = (await api.reconcile(thisStage)).reconciled.map(
            ({ matches: [addon] }) => addon
          );
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

  onMount(async () => {
    sources = await api.listSources();
    await refreshInstalled(true);
    // Switch over to reconciliation if no add-ons are installed
    if (!addons__Installed.length) {
      activeView = View.Reconcile;
    }
  });

  // Revert to `View.Installed` when the search box is emptied
  $: searchTerms || (activeView = View.Installed);
  // Reset search state in-between searches
  $: searchTerms ||
    ({ searchFromAlias, searchStrategy, searchStrategyExtra } = defaultSearchState);
  // Schedule a new search whenever the state changes
  $: (searchTerms || searchStrategy || searchFromAlias || searchStrategyExtra) &&
    searchDebounced();
  // Update add-on list according to view
  $: addons = activeView === View.Search ? addons__CombinedSearch : addons__Installed;
  // Re-count updates whenever `addons__Installed` is modified
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
    padding: 0.5em;
    border-radius: 0.5rem;
    box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-05);
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
    margin: 0 -0.5rem 0.5rem;
    padding: 0 1rem;
    font-size: 0.85em;
    background-image: linear-gradient(45deg, rgba(pink, 0.2), rgba(orange, 0.2));
    color: var(--inverse-color-tone-10);

    p {
      margin: 0.75rem 0;
    }

    :global(.icon) {
      width: 3rem;
      height: 3rem;
      fill: var(--inverse-color-tone-10);
    }
  }

  .addon-list {
    @include unstyle-list;

    li {
      border-radius: 4px;

      + li {
        margin-top: 4px;
      }

      &:nth-child(odd) {
        background-color: var(--inverse-color-alpha-05);
      }
    }
  }
</style>

{#if isActive}
  <AddonListNav
    on:keydown={(e) => e.key === 'Enter' && search()}
    on:requestRefresh={() => refreshInstalled()}
    on:requestUpdateAll={() => update(true)}
    on:requestReconcileStepBackward={() => goToPrevReconcileStage()}
    on:requestReconcileStepForward={() => goToNextReconcileStage()}
    on:requestInstallReconciled={() => installReconciled(reconcileStage, reconcileSelections)}
    on:requestAutomateReconciliation={() => installReconciled(reconcileStage, reconcileSelections, true)}
    bind:activeView
    bind:addonsCondensed
    bind:search__searchTerms={searchTerms}
    bind:search__fromAlias={searchFromAlias}
    bind:search__searchStrategy={searchStrategy}
    bind:search__searchStrategyExtra={searchStrategyExtra}
    search__isSearching={searchesInProgress > 0}
    installed__isRefreshing={refreshInProgress}
    installed__outdatedAddonCount={outdatedAddonCount}
    reconcile__isInstalling={reconcileInstallationInProgress}
    reconcile__canStepBackward={!!getReconcilePrevStage(reconcileStage)}
    reconcile__canStepForward={!!getReconcileNextStage(reconcileStage)} />
  <div class="addon-list-wrapper" class:prevent-scrolling={!!modal}>
    {#if modal === 'rollback'}
      <RollbackModal
        on:requestRollback={(event) => update([event.detail])}
        bind:show={modal}
        {addonListEl}
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
      <ul class="addon-list" bind:this={addonListEl}>
        {#each addons.map(attachTokentoAddon) as [addon, otherAddon, token] (token)}
          <li animate:flip={{ duration: 200 }}>
            <AddonComponent
              on:requestInstall={() => install([addonToDefn(otherAddon)])}
              on:requestUpdate={() => update([addonToDefn(otherAddon)])}
              on:requestRemove={() => remove([addonToDefn(addon)])}
              on:requestShowRollbackModal={() => showModal('rollback', addon)}
              on:showGenericAddonContextMenu={() => showGenericAddonContextMenu(addon)}
              on:showInstallAddonContextMenu={() => showInstallAddonContextMenu(otherAddon)}
              {addon}
              {otherAddon}
              isOutdated={otherAddon && addon.version !== otherAddon.version}
              supportsRollback={!!sources[addon.source]?.supports_rollback}
              beingModified={addonsBeingModified.includes(token)}
              showCondensed={addonsCondensed}
              refreshing={refreshInProgress} />
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}
