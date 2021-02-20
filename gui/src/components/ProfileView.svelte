<script context="module" lang="ts">
  import type {
    Addon,
    AddonWithMeta,
    Api,
    Config,
    Defn,
    ReconcileResult,
    SuccessResult,
    AnyResult,
    Sources,
  } from "../api";
  import { ReconciliationStage, Strategy, addonToDefn } from "../api";
  import { SEARCH_LIMIT, View } from "../constants";
  import { ipcRenderer } from "../ipc";
  import { profiles } from "../store";
  import { faQuestion } from "@fortawesome/free-solid-svg-icons";
  import lodash from "lodash";
  import { onMount, tick } from "svelte";
  import { flip } from "svelte/animate";
  import { fade } from "svelte/transition";
  import AddonComponent from "./Addon.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import RollbackModal from "./RollbackModal.svelte";
  import Icon from "./SvgIcon.svelte";

  // Two-tuple of reference and resolved add-on.  When listing installed add-ons
  // the reference add-on is the installed add-on.  If an installed add-on
  // cannot be resolved the resolved add-on is identical to the reference add-on
  // which is the installed add-on.
  // When searching for add-ons the reference add-on is the installed
  // add-on if the add-on is installed.  Otherwise it is the same as the
  // resolved add-on.  Reference add-ons must have an `__installed__` property
  // set to either true or false (see `AddonWithMeta`).
  type AddonTuple = readonly [AddonWithMeta, Addon];

  type CreateTokenSignature = {
    (addon: Addon): string;
    (defn: Defn): string;
  };

  const createAddonToken: CreateTokenSignature = (value: Addon | Defn) =>
    [value.source, (value as Addon).id || (value as Defn).alias].join(":");

  const attachTokentoAddon = ([addon, otherAddon]: AddonTuple): [AddonWithMeta, Addon, string] => [
    addon,
    otherAddon,
    createAddonToken(addon),
  ];

  const isSameAddon = ([thisAddon]: AddonTuple, otherAddon: Addon) =>
    thisAddon.source === otherAddon.source && thisAddon.id === otherAddon.id;

  const markAddonInstalled = (addon: Addon, installed = true): AddonWithMeta => ({
    __installed__: installed,
    ...addon,
  });

  const notifyOfFailures = (method: string, combinedResult: (readonly [Addon, AnyResult])[]) => {
    for (const [addon, result] of combinedResult) {
      if (result.status !== "success") {
        new Notification(`failed to ${method} ${addon.name} (${createAddonToken(addon)})`, {
          body: result.message,
        });
      }
    }
  };

  const reconcileStages = Object.values(ReconciliationStage);

  const getPrevReconcileStage = (stage: ReconciliationStage) =>
    reconcileStages[reconcileStages.indexOf(stage) - 1];

  const getNextReconcileStage = (stage: ReconciliationStage) =>
    reconcileStages[reconcileStages.indexOf(stage) + 1];

  const defaultSearchState: {
    searchTerms: string;
    searchFromAlias: boolean;
    searchSource: string | null;
    searchStrategy: Strategy;
    searchVersion: string;
  } = {
    searchTerms: "",
    searchFromAlias: false,
    searchSource: null,
    searchStrategy: Strategy.default,
    searchVersion: "",
  };
</script>

<script lang="ts">
  export let profile: string, api: Api, isActive: boolean, installedAddonCount: number;

  let sources: Sources;
  let uriSchemes: string[];

  let activeView: View = View.Installed;
  let addonsCondensed: boolean = false;

  let addons__Installed: AddonTuple[] = [];
  let addons__Search: Addon[] = [];
  let addons__CombinedSearch: AddonTuple[] = [];
  let outdatedAddonCount: number;
  let addonsBeingModified: string[] = []; // revisit

  let {
    searchTerms,
    searchFromAlias,
    searchSource,
    searchStrategy,
    searchVersion,
  } = defaultSearchState;

  let reconcileStage: ReconciliationStage = reconcileStages[0];
  let reconcileSelections: Addon[];

  let refreshInProgress: boolean = false;
  let searchesInProgress: number = 0;
  let reconcileInstallationInProgress: boolean = false;

  let rollbackModal: boolean = false;
  let rollbackModalProps: { addon: Addon };
  let addonListEl: HTMLElement;

  const countUpdates = () =>
    (outdatedAddonCount = addons__Installed.reduce(
      (val, [thisAddon, otherAddon]) =>
        val + (otherAddon && thisAddon.version !== otherAddon.version ? 1 : 0),
      0
    ));

  const regenerateCombinedSearchAddons = () => {
    const combinedAddons = addons__Search.map((addon) => {
      const installedAddon = addons__Installed.find((installedAddon) =>
        isSameAddon(installedAddon, addon)
      );
      return [installedAddon?.[0] || markAddonInstalled(addon, false), addon] as const;
    });
    addons__CombinedSearch = combinedAddons;
  };

  const modifyAddons = async (
    method: "install" | "update" | "remove" | "pin",
    addons: Addon[],
    extraParams: { [key: string]: any } = {}
  ) => {
    const ids = addons.map(createAddonToken);
    addonsBeingModified = [...addonsBeingModified, ...ids];

    try {
      const modifyResults = await api.modifyAddons(method, addons.map(addonToDefn), extraParams);
      const modifiedAddons = modifyResults
        .filter((result): result is SuccessResult => result.status === "success")
        .map(({ addon }) => addon);
      if (modifiedAddons) {
        const installedAddons = [...addons__Installed];
        // Reversing `modifiedAddons` so that new add-ons will
        // be prepended in alphabetical order
        for (const addon of [...modifiedAddons].reverse()) {
          const newAddon = [markAddonInstalled(addon, method !== "remove"), addon] as const;
          const index = addons__Installed.findIndex((value) => isSameAddon(value, addon));
          if (index === -1) {
            installedAddons.unshift(newAddon);
          } else {
            installedAddons[index] = newAddon;
          }
        }
        addons__Installed = installedAddons;
        regenerateCombinedSearchAddons();
      }
      notifyOfFailures(
        method,
        addons.map((a, i) => [a, modifyResults[i]])
      );
    } finally {
      addonsBeingModified = lodash.difference(addonsBeingModified, ids);
    }
  };

  const installAddons = async (addons: Addon[], replace = false) => {
    await modifyAddons("install", addons, { replace: replace });
  };

  type UpdateAddonsSignature = {
    (defns: Addon[]): Promise<void>;
    (all: true): Promise<void>;
  };

  const updateAddons: UpdateAddonsSignature = async (value: Addon[] | true) => {
    if (value === true) {
      const outdatedAddons = addons__Installed
        .filter(
          ([{ version: thisVersion }, { version: otherVersion }]) => thisVersion !== otherVersion
        )
        .map(([, addon]) => addon);
      await modifyAddons("update", outdatedAddons);
    } else {
      await modifyAddons("update", value);
    }
  };

  const removeAddons = async (addons: Addon[], keepFolders: boolean) => {
    await modifyAddons("remove", addons, { keep_folders: keepFolders });
  };

  const pinAddons = async (addons: Addon[]) => {
    await modifyAddons("pin", addons);
  };

  const isSearchFromAlias = () => {
    return uriSchemes.some((s) => searchTerms.startsWith(s));
  };

  const search = async () => {
    searchesInProgress++;
    try {
      const searchTermsSnapshot = searchTerms;
      if (searchTermsSnapshot) {
        let results: AnyResult[];

        if (searchFromAlias) {
          results = await api.resolve([
            {
              source: "*",
              alias: searchTermsSnapshot,
              strategy: searchStrategy,
              version: searchVersion,
            },
          ]);
        } else {
          const searchResults = await api.search(
            searchTermsSnapshot,
            SEARCH_LIMIT,
            searchSource ? [searchSource] : null
          );

          if (searchTermsSnapshot !== searchTerms) {
            return;
          }

          const defns = searchResults.map((r) => ({
            source: r.source,
            alias: r.id,
            strategy: searchStrategy,
            version: searchVersion,
          }));
          results = await api.resolve(defns);
        }

        if (searchTermsSnapshot !== searchTerms) {
          return;
        }

        addons__Search = results
          .filter((result): result is SuccessResult => result.status === "success")
          .map(({ addon }) => addon);
        regenerateCombinedSearchAddons();
        activeView = View.Search;
      }
    } finally {
      searchesInProgress--;
    }
  };

  const refreshInstalled = async (flash = false) => {
    if (!refreshInProgress) {
      refreshInProgress = true;
      try {
        const installedAddons = (await api.list()).map((addon) => markAddonInstalled(addon));
        if (flash) {
          addons__Installed = installedAddons.map((a) => [a, a]);
        }
        const resolveResults = await api.resolve(installedAddons.map(addonToDefn));
        const addonsToResults = installedAddons.map((a, i) => [a, resolveResults[i]] as const);
        addons__Installed = lodash.sortBy(
          addonsToResults.map(([thisAddon, result]) => [
            thisAddon,
            result.status === "success" ? result?.addon : thisAddon,
          ]),
          // Lift outdated add-ons to the top of ht list
          ([thisAddon, { version: otherVersion }]) => [
            thisAddon.version === otherVersion,
            thisAddon.name.toLowerCase(),
          ]
        );
        notifyOfFailures("resolve", addonsToResults);
      } finally {
        // Keep actions disabled for a little while longer while the add-ons
        // are being reshuffled to prevent misclicking
        setTimeout(() => (refreshInProgress = false), 500);
      }
    }
  };

  const showRollbackModal = (addon: Addon) => {
    rollbackModalProps = { addon: addon };
    rollbackModal = true;
  };

  const showGenericAddonContextMenu = async (addon: Addon) => {
    const selection = await ipcRenderer.invoke(
      "get-action-from-context-menu",
      [
        { id: "open-url", label: "Open in browser" },
        { id: "reveal-folder", label: "Reveal folder" },
        sources[addon.source]?.supports_rollback &&
          (addon.options.strategy === Strategy.version
            ? { id: "unpin", label: "Unpin" }
            : { id: "pin", label: "Pin" }),
        { id: "unreconcile", label: "Unreconcile" },
        { id: "lookup", label: "Resolve" },
      ].filter(Boolean)
    );
    switch (selection) {
      case "open-url":
        ipcRenderer.send("open-url", addon.url);
        break;
      case "reveal-folder":
        ipcRenderer.send("reveal-folder", [
          ($profiles.get(profile) as Config).addon_dir,
          addon.folders[0].name,
        ]);
        break;
      case "pin":
      case "unpin":
        const pinnedAddon = {
          ...addon,
          options: { strategy: selection === "pin" ? Strategy.version : Strategy.default },
        };
        await pinAddons([pinnedAddon]);
        break;
      case "unreconcile":
        await removeAddons([addon], true);
        break;
      case "lookup":
        searchTerms = "";
        await tick();
        [searchTerms, searchFromAlias, searchStrategy, searchVersion] = [
          createAddonToken(addon),
          true,
          addon.options.strategy,
          addon.version,
        ];
        break;
      default:
        break;
    }
  };

  const showInstallAddonContextMenu = async (addon: Addon) => {
    const selection = await ipcRenderer.invoke("get-action-from-context-menu", [
      // This should be pulled out of here and made interactive when installing
      { id: "install-and-replace", label: "Install and replace" },
      { id: "lookup", label: "Resolve" },
    ]);
    if (selection === "install-and-replace") {
      await installAddons([addon], true);
    } else if (selection === "lookup") {
      searchTerms = "";
      await tick();
      [searchTerms, searchFromAlias, searchStrategy, searchVersion] = [
        createAddonToken(addon),
        true,
        addon.options.strategy,
        addon.version,
      ];
    }
  };

  const goToPrevReconcileStage = () => (reconcileStage = getPrevReconcileStage(reconcileStage));

  const goToNextReconcileStage = () => (reconcileStage = getNextReconcileStage(reconcileStage));

  const prepareReconcile = async (thisStage: ReconciliationStage) => {
    const stages = lodash.dropWhile(reconcileStages, (s) => s !== thisStage);
    for (const stage of stages) {
      console.debug(profile, "- trying", stage);
      const results = await api.reconcile(stage);
      if (results.reconciled.length || !getNextReconcileStage(stage)) {
        reconcileStage = stage;
        reconcileSelections = [];
        return results;
      }
    }
    console.debug(profile, "- no stages in", stages, "from", thisStage);
    return {} as ReconcileResult;
  };

  const installReconciled = async (
    thisStage: ReconciliationStage,
    theseSelections: Addon[],
    recursive?: boolean
  ) => {
    reconcileInstallationInProgress = true;
    try {
      console.debug(profile, "- installing selections from", thisStage);
      await installAddons(theseSelections.filter(Boolean), true);
      const nextStage = getNextReconcileStage(thisStage);
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
    uriSchemes = [...Object.keys(sources), "http", "https"].map((s) => `${s}:`);
    await refreshInstalled(true);
    // Switch over to reconciliation if no add-ons are installed
    if (!addons__Installed.length) {
      activeView = View.Reconcile;
    }
  });

  // Revert to `View.Installed` when the search box is empty
  $: searchTerms ||
    (console.debug(profile, "- restoring add-on view"), (activeView = View.Installed));
  // Reset search params in-between searches
  $: searchTerms ||
    (console.debug(profile, "- resetting search values"),
    ({ searchFromAlias, searchSource, searchStrategy, searchVersion } = defaultSearchState));
  // Upddate `searchFromAlias` whenever the `searchTerms` change
  $: searchTerms &&
    (searchFromAlias =
      (console.debug(profile, "- updating `searchFromAlias`"), isSearchFromAlias()));
  // Schedule a new search whenever the search params change
  $: (searchFromAlias || searchSource || searchStrategy || searchVersion) &&
    (console.debug(profile, "- triggering search"), search());
  // Update add-on list according to view
  $: addons = activeView === View.Search ? addons__CombinedSearch : addons__Installed;
  // Recount updates whenever `addons__Installed` is modified
  $: addons__Installed && (console.debug(profile, "- recounting updates"), countUpdates());
  // Propagate `installedAddonCount` when profile is active
  $: isActive &&
    (installedAddonCount =
      (console.debug(profile, "- recounting installed add-ons"), addons__Installed.length));
</script>

{#if isActive}
  <AddonListNav
    {profile}
    {sources}
    on:keydown={(e) => e.key === "Enter" && search()}
    on:requestRefresh={() => refreshInstalled()}
    on:requestUpdateAll={() => updateAddons(true)}
    on:requestReconcileStepBackward={() => goToPrevReconcileStage()}
    on:requestReconcileStepForward={() => goToNextReconcileStage()}
    on:requestInstallReconciled={() => installReconciled(reconcileStage, reconcileSelections)}
    on:requestAutomateReconciliation={() =>
      installReconciled(reconcileStage, reconcileSelections, true)}
    bind:activeView
    bind:addonsCondensed
    bind:search__searchTerms={searchTerms}
    bind:search__fromAlias={searchFromAlias}
    bind:search__searchSource={searchSource}
    bind:search__searchStrategy={searchStrategy}
    bind:search__searchVersion={searchVersion}
    search__isSearching={searchesInProgress > 0}
    installed__isRefreshing={refreshInProgress}
    installed__outdatedAddonCount={outdatedAddonCount}
    reconcile__isInstalling={reconcileInstallationInProgress}
    reconcile__canStepBackward={!!getPrevReconcileStage(reconcileStage)}
    reconcile__canStepForward={!!getNextReconcileStage(reconcileStage)}
  />
  <div class="addon-list-wrapper" class:prevent-scrolling={rollbackModal}>
    {#if rollbackModal}
      <RollbackModal
        on:requestRollback={(event) => updateAddons([event.detail])}
        bind:show={rollbackModal}
        {addonListEl}
        {...rollbackModalProps}
      />
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
            {#each result.reconciled.concat(result.unreconciled) as { folders, matches }, idx}
              <li>
                <AddonStub
                  bind:selections={reconcileSelections}
                  {folders}
                  choices={matches}
                  {idx}
                />
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
              on:requestInstall={() => installAddons([otherAddon])}
              on:requestUpdate={() => updateAddons([otherAddon])}
              on:requestRemove={() => removeAddons([addon], false)}
              on:requestShowRollbackModal={() => showRollbackModal(addon)}
              on:showGenericAddonContextMenu={() => showGenericAddonContextMenu(addon)}
              on:showInstallAddonContextMenu={() => showInstallAddonContextMenu(otherAddon)}
              {addon}
              {otherAddon}
              isOutdated={addon.version !== otherAddon.version}
              supportsRollback={!!sources[addon.source]?.supports_rollback}
              beingModified={addonsBeingModified.includes(token)}
              showCondensed={addonsCondensed}
              installed__isRefreshing={refreshInProgress}
            />
          </li>
        {/each}
      </ul>
    {/if}
  </div>
{/if}

<style lang="scss">
  @import "scss/vars";

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
    box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);
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
