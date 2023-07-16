<script context="module" lang="ts">
  import { faQuestion } from "@fortawesome/free-solid-svg-icons";
  import * as commonmark from "commonmark";
  import lodash from "lodash";
  import { onMount } from "svelte";
  import { flip } from "svelte/animate";
  import { fade, slide } from "svelte/transition";
  import type {
    Addon,
    AnyResult,
    CatalogueEntry,
    Defn,
    ErrorResult,
    Source,
    Strategies,
    SuccessResult,
  } from "../api";
  import { addonToDefn, ChangelogFormat, ReconciliationStage, Strategy } from "../api";
  import { AddonAction, ListFormat, View } from "../constants";
  import { alerts, api, profiles } from "../stores";
  import AddonComponent from "./Addon.svelte";
  import AddonContextMenu from "./AddonContextMenu.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import ChangelogModalContents from "./ChangelogModalContents.svelte";
  import Modal from "./modal/Modal.svelte";
  import RollbackModalContents from "./RollbackModalContents.svelte";
  import SearchOptionsModalContents from "./SearchOptionsModalContents.svelte";
  import Icon from "./SvgIcon.svelte";
  import type { ComponentProps } from "svelte";

  type AddonTriplet = readonly [addon: Addon, otherAddon: Addon, isInstalled: boolean];

  const createAddonToken = (value: Addon | Defn) =>
    [value.source, (value as Addon).id || (value as Defn).alias].join(":");

  const tripletWithAddonToken = ([addon, ...rest]: AddonTriplet) =>
    [addon, ...rest, createAddonToken(addon)] as const;

  const isSameAddon = (thisAddon: Addon, otherAddon: Addon) =>
    thisAddon.source === otherAddon.source && thisAddon.id === otherAddon.id;

  const reconcileStages = Object.values(ReconciliationStage);

  export type SearchStrategies = {
    [K in keyof Strategies]: NonNullable<
      Strategies[K] extends boolean | null ? boolean : Strategies[K]
    >;
  };

  const defaultSearchOptions: {
    fromAlias: boolean;
    limit: number;
    sources: string[];
    startDate: string | null;
    strategies: SearchStrategies;
  } = {
    fromAlias: false,
    limit: 20,
    sources: [],
    startDate: null,
    strategies: {
      [Strategy.AnyFlavour]: false,
      [Strategy.AnyReleaseType]: false,
      [Strategy.VersionEq]: "",
    },
  };

  const htmlify = (changelog: string, format: ChangelogFormat) => {
    if (format === ChangelogFormat.Markdown) {
      return {
        renderAsHtml: true,
        changelog: new commonmark.HtmlRenderer().render(new commonmark.Parser().parse(changelog)),
      };
    } else {
      return {
        renderAsHtml: format === ChangelogFormat.Html,
        changelog,
      };
    }
  };

  const cycleListFormat = (currentFormat: ListFormat): ListFormat => {
    const listFormat = currentFormat + 1;
    return ListFormat[listFormat] ? listFormat : ListFormat.Dense;
  };
</script>

<script lang="ts">
  export let profile: string, isActive: boolean, statusMessage: string;

  const config = $profiles[profile];
  const profileApi = $api.withProfile(profile);

  let sources: { [source: string]: Source } = {};
  let uriSchemes: string[];

  let activeView: View = View.Installed;
  let installedListFormat = ListFormat.Compact;
  let searchListFormat = ListFormat.Expanded;

  let filteredCatalogueEntries: CatalogueEntry[] = [];
  let addonsFromSearch: Addon[] = [];
  let installedOutdatedCount: number;
  let installedAddonsBeingModified: string[] = [];

  const addonsByView = {
    [View.Installed]: [] as AddonTriplet[],
    [View.FilterInstalled]: [] as AddonTriplet[],
    [View.Search]: [] as AddonTriplet[],
  };

  let addonDownloadProgress: { [token: string]: number } = {};

  let searchTerms = "";
  let searchFilterInstalled = false;
  let searchOptions = lodash.cloneDeep(defaultSearchOptions);
  let searchIsDirty = false;

  let reconcileStage: ReconciliationStage = reconcileStages[0];
  let reconcileSelections: Addon[] = [];

  let reconcileInstalledAddons: Addon[];
  let reconcileInstalledSelections: Addon[];

  let installedIsRefreshing = false;
  let searchesInProgress = 0;
  let reconcileInstallationInProgress = false;

  let modal:
    | { id: "changelog"; dynamicProps: ComponentProps<ChangelogModalContents> }
    | { id: "rollback"; dynamicProps: ComponentProps<RollbackModalContents> }
    | { id: "searchOptions" }
    | undefined;

  let addonContextMenu: AddonContextMenu;

  const alertAddonOpFailed = (method: string, combinedResult: (readonly [Addon, AnyResult])[]) => {
    const newAlerts = combinedResult
      .filter((c): c is [Addon, ErrorResult] => c[1].status !== "success")
      .map(([a, r]) => ({
        heading: `failed to ${method} ${a.name} (${createAddonToken(a)})`,
        message: r.message,
      }));
    $alerts = {
      ...$alerts,
      [profile]: [...newAlerts, ...($alerts[profile] ?? [])],
    };
  };

  const countInstalled = () => {
    return addonsByView[View.Installed].reduce((val, [, , installed]) => val + +installed, 0);
  };

  const countUpdates = () => {
    return addonsByView[View.Installed].reduce(
      (val, [thisAddon, otherAddon]) =>
        val + (otherAddon && thisAddon.version !== otherAddon.version ? 1 : 0),
      0
    );
  };

  const regenerateFilteredAddons = () => {
    return addonsByView[View.Installed].filter(([a]) =>
      filteredCatalogueEntries.some((e) => a.source === e.source && a.id === e.id)
    );
  };

  const regenerateSearchAddons = () => {
    return addonsFromSearch.map((addon) => {
      const installedAddonTriplet = addonsByView[View.Installed].find(([a]) =>
        isSameAddon(a, addon)
      );
      if (installedAddonTriplet) {
        const [installedAddon, , isInstalled] = installedAddonTriplet;
        return [installedAddon, addon, isInstalled] as const;
      }
      return [addon, addon, false] as const;
    });
  };

  const withDownloadProgress = async <T>(promise: Promise<T>, pollingInterval: number) => {
    const ticker = setInterval(async () => {
      const downloadProgress = await profileApi.getDownloadProgress();
      addonDownloadProgress = Object.fromEntries(
        downloadProgress.map(({ defn, progress }) => [createAddonToken(defn), progress])
      );
    }, pollingInterval);

    try {
      return await promise;
    } finally {
      clearInterval(ticker);
    }
  };

  const modifyAddons = async (
    method: "install" | "update" | "remove" | "pin",
    addons: Addon[],
    extraParams: { [key: string]: unknown } = {}
  ) => {
    const addonTokens = addons.map(createAddonToken);
    installedAddonsBeingModified = [...installedAddonsBeingModified, ...addonTokens];

    try {
      const modifyResults = await withDownloadProgress(
        profileApi.modifyAddons(method, addons.map(addonToDefn), extraParams),
        1000
      );

      const modifiedAddons = modifyResults
        .filter((result): result is SuccessResult => result.status === "success")
        .map(({ addon }) => addon);
      if (modifiedAddons.length) {
        const installedAddons = [...addonsByView[View.Installed]];

        // Reversing `modifiedAddons` for new add-ons to be prepended in alphabetical order
        for (const addon of [...modifiedAddons].reverse()) {
          const newAddon = [addon, addon, method !== "remove"] as const;
          const index = addonsByView[View.Installed].findIndex(([a]) => isSameAddon(a, addon));
          if (index === -1) {
            installedAddons.unshift(newAddon);
          } else {
            installedAddons[index] = newAddon;
          }
        }

        addonsByView[View.Installed] = installedAddons;
      }

      alertAddonOpFailed(
        method,
        addons.map((a, i) => [a, modifyResults[i]])
      );
    } finally {
      installedAddonsBeingModified = lodash.difference(installedAddonsBeingModified, addonTokens);
    }
  };

  const installAddons = async (addons: Addon[], replace = false) => {
    await modifyAddons("install", addons, { replace: replace });
  };

  const updateAddons = async (addons: Addon[] | true) => {
    if (addons === true) {
      const outdatedAddons = addonsByView[View.Installed]
        .filter(
          ([{ version: thisVersion }, { version: otherVersion }]) => thisVersion !== otherVersion
        )
        .map(([, addon]) => addon);
      await modifyAddons("update", outdatedAddons);
    } else {
      await modifyAddons("update", addons);
    }
  };

  const removeAddons = async (addons: Addon[], keepFolders: boolean) => {
    await modifyAddons("remove", addons, { keep_folders: keepFolders });
  };

  const pinAddons = async (addons: Addon[]) => {
    await modifyAddons("pin", addons);
  };

  const isSearchFromAlias = () => {
    return uriSchemes?.some((s) => searchTerms.startsWith(s));
  };

  const search = async () => {
    searchesInProgress++;

    try {
      const searchTermsSnapshot = searchTerms;

      if (searchTermsSnapshot) {
        let results: AnyResult[];

        const condensedStrategies = Object.fromEntries(
          Object.entries(searchOptions.strategies).map(([k, v]) => [k, v || null])
        ) as Strategies;

        if (searchOptions.fromAlias) {
          let source = "*",
            alias = searchTermsSnapshot;

          const colonIndex = searchTermsSnapshot.indexOf(":");
          if (colonIndex !== -1) {
            const sourceCandidate = searchTermsSnapshot.slice(0, colonIndex);
            if (sourceCandidate in sources) {
              source = sourceCandidate;
              alias = searchTermsSnapshot.slice(colonIndex + 1);
            }
          }

          results = await profileApi.resolve([
            {
              source,
              alias,
              strategies: condensedStrategies,
            },
          ]);
        } else {
          const catalogueEntries = await profileApi.search(
            searchTermsSnapshot,
            searchOptions.limit,
            searchOptions.sources,
            searchOptions.startDate,
            searchFilterInstalled
          );

          if (searchTermsSnapshot !== searchTerms) {
            return;
          }

          if (searchFilterInstalled) {
            filteredCatalogueEntries = catalogueEntries;
            activeView = View.FilterInstalled;
            return;
          }

          const defns = catalogueEntries.map((e) => ({
            source: e.source,
            alias: e.id,
            strategies: condensedStrategies,
          }));
          results = await profileApi.resolve(defns);
        }

        if (searchTermsSnapshot !== searchTerms) {
          return;
        }

        addonsFromSearch = results
          .filter((result): result is SuccessResult => result.status === "success")
          .map(({ addon }) => addon);
        activeView = View.Search;
      }
    } finally {
      searchesInProgress--;
    }
  };

  const refreshInstalled = async (flash = false) => {
    if (!installedIsRefreshing) {
      installedIsRefreshing = true;
      try {
        const installedAddons = await profileApi.list();
        if (flash) {
          addonsByView[View.Installed] = installedAddons.map((a) => [a, a, true]);
        }
        const resolveResults = await profileApi.resolve(installedAddons.map(addonToDefn));
        const addonsToResults = installedAddons.map((a, i) => [a, resolveResults[i]] as const);
        addonsByView[View.Installed] = lodash.sortBy(
          addonsToResults.map(([thisAddon, result]) => [
            thisAddon,
            result.status === "success" ? result.addon : thisAddon,
            true,
          ]),
          // Haul outdated add-ons to the top
          ([thisAddon, { version: otherVersion }]) => [
            thisAddon.version === otherVersion,
            thisAddon.name.toLowerCase(),
          ]
        );
        alertAddonOpFailed("resolve", addonsToResults);
      } finally {
        // Keep actions disabled for a little while longer while the add-ons
        // are being reshuffled to prevent misclicking
        setTimeout(() => (installedIsRefreshing = false), 500);
      }
    }
  };

  const showChangelogModal = async (addon: Addon) => {
    const changelog = await profileApi.getChangelog(addon.source, addon.changelog_url);
    modal = {
      id: "changelog",
      dynamicProps: htmlify(changelog, sources[addon.source].changelog_format),
    };
  };

  const showRollbackModal = (addon: Addon) => {
    modal = {
      id: "rollback",
      dynamicProps: { addon },
    };
  };

  const showSearchOptionsModal = () => {
    modal = {
      id: "searchOptions",
    };
  };

  const resetModal = () => {
    modal = undefined;
  };

  const showAddonContextMenu = (
    addon: Addon,
    installed: boolean,
    { clientX, clientY }: MouseEvent
  ) => {
    addonContextMenu.show(
      { x: clientX, y: clientY },
      {
        addon,
        installed,
        supportsRollback: supportsRollback(addon),
      }
    );
  };

  const handleAddonContextMenuSelection = (addon: Addon, selection: AddonAction) => {
    switch (selection) {
      case AddonAction.VisitHomepage:
        profileApi.openUrl(addon.url);
        break;

      case AddonAction.ViewChangelog:
        showChangelogModal(addon);
        break;

      case AddonAction.RevealFolder: {
        const {
          folders: [{ name: folderName }],
        } = addon;
        profileApi.revealFolder([config.addon_dir, folderName]);

        break;
      }

      case AddonAction.Resolve: {
        searchOptions = {
          ...lodash.cloneDeep(defaultSearchOptions),
          fromAlias: true,
          strategies: {
            ...addon.options,
            [Strategy.VersionEq]: addon.options[Strategy.VersionEq] ? addon.version : "",
          },
        };
        searchTerms = `${addon.source}:${addon.slug}`;
        search();

        break;
      }

      case AddonAction.Rollback:
        showRollbackModal(addon);
        break;

      case AddonAction.Pin:
      case AddonAction.Unpin: {
        const pinnedAddon = lodash.merge(addon);
        pinnedAddon.options.version_eq = selection === AddonAction.Pin;
        pinAddons([pinnedAddon]);

        break;
      }

      case AddonAction.Unreconcile:
        removeAddons([addon], true);
        break;

      case AddonAction.InstallAndReplace:
        installAddons([addon], true);
        break;
    }
  };

  const reconcile = async (fromStage: ReconciliationStage) => {
    for (const [index, stage] of Array.from(reconcileStages.entries()).slice(
      reconcileStages.indexOf(fromStage)
    )) {
      const results = await profileApi.reconcile(stage);
      if (results.some((r) => r.matches.length) || !(index + 1 in reconcileStages)) {
        return [stage, results] as const;
      }
    }
  };

  const prepareReconcile = async (fromStage: ReconciliationStage) => {
    const maybeResults = await reconcile(fromStage);
    if (maybeResults) {
      [reconcileStage] = maybeResults;
      const [, reconcileResult] = maybeResults;
      reconcileSelections = [];
      return reconcileResult;
    }
  };

  const installReconciled = async (
    fromStage: ReconciliationStage,
    theseSelections: Addon[],
    recursive?: boolean
  ) => {
    reconcileInstallationInProgress = true;
    try {
      console.debug(profile, "installing selections from", fromStage);
      await installAddons(theseSelections.filter(Boolean), true);
      const nextStage = reconcileStages[reconcileStages.indexOf(fromStage) + 1];
      if (nextStage) {
        if (recursive) {
          const nextSelections = (await profileApi.reconcile(fromStage))
            .filter((r) => r.matches.length)
            .map(({ matches: [addon] }) => addon);
          await installReconciled(nextStage, nextSelections, true);
        } else {
          reconcileStage = nextStage;
        }
      } else {
        // We might be at `reconcileStage[0]` if `installReconciled` was called recursively
        reconcileStage = reconcileStages[reconcileStages.indexOf(fromStage) || 0];
      }
    } finally {
      reconcileInstallationInProgress = false;
    }
  };

  const prepareReconcileInstalled = async () => {
    const alternativeDefnsPerAddon = await profileApi.getReconcileInstalledCandidates();
    reconcileInstalledAddons = alternativeDefnsPerAddon.map(
      ({ installed_addon }) => installed_addon
    );
    reconcileInstalledSelections = [];
    return alternativeDefnsPerAddon;
  };

  const installReconciledInstalled = async () => {
    reconcileInstallationInProgress = true;
    try {
      const addonsToRereconcile = reconcileInstalledSelections
        .map((a, i) => [a, reconcileInstalledAddons[i]] as const)
        .filter(([a, b]) => a && !isSameAddon(a, b));
      await removeAddons(
        addonsToRereconcile.map(([, a]) => a),
        false
      );
      await installAddons(
        addonsToRereconcile.map(([a]) => a),
        false
      );
      activeView = View.Installed;
    } finally {
      reconcileInstallationInProgress = false;
    }
  };

  const supportsRollback = (addon: Addon) =>
    !!sources[addon.source]?.strategies.includes(Strategy.VersionEq);

  const resetSearchState = () => {
    searchOptions = lodash.cloneDeep(defaultSearchOptions);
  };

  const cycleDisplayedListFormat = () => {
    if (activeView === View.Installed || activeView === View.FilterInstalled) {
      installedListFormat = cycleListFormat(installedListFormat);
    } else if (activeView === View.Search) {
      searchListFormat = cycleListFormat(searchListFormat);
    }
  };

  onMount(async () => {
    sources = await profileApi.listSources();
    uriSchemes = [...Object.keys(sources), "http", "https"].map((s) => `${s}:`);
    await refreshInstalled(true);
    // Switch over to reconciliation if no add-ons are installed
    if (!addonsByView[View.Installed].length) {
      activeView = View.Reconcile;
    }
  });

  $: if (activeView !== View.Search && searchTerms === "") {
    console.debug(profile, "resetting search state");
    resetSearchState();
  }

  $: {
    searchFilterInstalled;

    console.debug(profile, "filter status changed, resetting search state");
    resetSearchState();
  }

  $: searchIsDirty = !lodash.isEqual(
    [searchOptions.sources, searchOptions.startDate, searchOptions.strategies],
    [defaultSearchOptions.sources, defaultSearchOptions.startDate, defaultSearchOptions.strategies]
  );

  $: {
    searchTerms;

    searchOptions.fromAlias =
      (console.debug(profile, "updating `searchFromAlias`"), isSearchFromAlias());
  }

  $: if (activeView === View.Reconcile) {
    reconcileStage = reconcileStages[0];
  }

  $: {
    addonsByView[View.Installed];

    console.debug(profile, "recounting updates");
    installedOutdatedCount = countUpdates();
  }

  $: {
    addonsByView[View.Installed], filteredCatalogueEntries;

    addonsByView[View.FilterInstalled] = regenerateFilteredAddons();
  }

  $: {
    addonsByView[View.Installed], addonsFromSearch;

    addonsByView[View.Search] = regenerateSearchAddons();
  }

  $: {
    addonsByView[View.Installed];

    console.debug(profile, "updating status message");

    if (isActive) {
      if (installedIsRefreshing) {
        statusMessage = "refreshing…";
      } else if (reconcileInstallationInProgress) {
        statusMessage = "installing…";
      } else {
        statusMessage = `installed add-ons: ${countInstalled()}`;
      }
    }
  }
</script>

{#if isActive}
  <div class="addon-list-wrapper">
    <div class="addon-list-nav-wrapper">
      <AddonListNav
        on:requestSearch={() => search()}
        on:requestShowSearchOptionsModal={() => showSearchOptionsModal()}
        on:requestRefresh={() => refreshInstalled()}
        on:requestUpdateAll={() => updateAddons(true)}
        on:requestInstallReconciled={() => installReconciled(reconcileStage, reconcileSelections)}
        on:requestAutomateReconciliation={() =>
          installReconciled(reconcileStage, reconcileSelections, true)}
        on:requestInstallReconciledInstalled={() => installReconciledInstalled()}
        on:requestCycleListFormat={() => cycleDisplayedListFormat()}
        bind:activeView
        bind:searchTerms
        bind:searchFilterInstalled
        bind:reconcileStage
        {searchIsDirty}
        {installedOutdatedCount}
        {reconcileInstallationInProgress}
        canReconcile={reconcileSelections.length > 0}
        isRefreshing={installedIsRefreshing}
        isModifying={installedAddonsBeingModified.length > 0}
        isSearching={searchesInProgress > 0}
      />
    </div>

    <AddonContextMenu
      bind:this={addonContextMenu}
      on:selectItem={({ detail: { addon, action } }) => {
        handleAddonContextMenuSelection(addon, action);
      }}
    />

    {#if modal}
      <Modal on:dismiss={resetModal}>
        {#if modal.id === "changelog"}
          <ChangelogModalContents {...modal.dynamicProps} />
        {:else if modal.id === "rollback"}
          <RollbackModalContents
            on:requestRollback={({ detail }) => updateAddons([detail])}
            {...modal.dynamicProps}
          />
        {:else if modal.id === "searchOptions"}
          <SearchOptionsModalContents
            flavour={config.game_flavour}
            {sources}
            {searchFilterInstalled}
            bind:searchOptions
            on:requestSearch={search}
            on:requestReset={resetSearchState}
          />
        {/if}
      </Modal>
    {/if}

    {#if activeView === View.Reconcile}
      {#await prepareReconcile(reconcileStage)}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then result}
        {#if result && result.length}
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
            {#each result as { folders, matches }, idx}
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
    {:else if activeView === View.ReconcileInstalled}
      {#await prepareReconcileInstalled()}
        <div class="placeholder" in:fade>
          <div>Hold on tight!</div>
        </div>
      {:then result}
        {#if result.length}
          <ul class="addon-list">
            {#each result as { installed_addon, alternative_addons }, idx}
              <li>
                <AddonStub
                  selections={reconcileInstalledSelections}
                  folders={[{ name: installed_addon.name, version: "" }]}
                  choices={[installed_addon, ...alternative_addons]}
                  {idx}
                  expanded={true}
                />
              </li>
            {/each}
          </ul>
        {:else}
          <div class="placeholder" in:fade>
            <div>No alternative sources available.</div>
          </div>
        {/if}
      {/await}
    {:else}
      {#key activeView}
        <ul class="addon-list" in:slide={{ duration: 250 }}>
          {#each addonsByView[activeView].map(tripletWithAddonToken) as [addon, otherAddon, isInstalled, token] (token)}
            <li animate:flip={{ duration: 250 }}>
              <AddonComponent
                on:requestInstall={() => installAddons([otherAddon])}
                on:requestUpdate={() => updateAddons([otherAddon])}
                on:requestRemove={() => removeAddons([addon], false)}
                on:requestShowChangelogModal={() => showChangelogModal(otherAddon)}
                on:requestShowAddonContextMenu={({ detail: { mouseEvent } }) =>
                  showAddonContextMenu(isInstalled ? addon : otherAddon, isInstalled, mouseEvent)}
                {addon}
                {otherAddon}
                {isInstalled}
                beingModified={installedAddonsBeingModified.includes(token)}
                format={activeView === View.Search ? searchListFormat : installedListFormat}
                isRefreshing={installedIsRefreshing}
                downloadProgress={addonDownloadProgress[token] || 0}
              />
            </li>
          {/each}
        </ul>
      {/key}
    {/if}
  </div>
{/if}

<style lang="scss">
  @use "scss/vars";

  .placeholder {
    display: flex;
    flex-grow: 1;
    place-items: center;

    > div {
      flex-grow: 1;
      text-align: center;
    }
  }

  .addon-list-wrapper {
    @extend %stretch-vertically;
    position: relative;
    overflow-y: auto;
    -webkit-user-select: none;
    user-select: none;
  }

  .addon-list-nav-wrapper,
  .addon-list {
    padding: 0 0.8em;
  }

  .addon-list-nav-wrapper {
    @extend %blur-background;
    background-color: var(--base-color-tone-a-alpha-85);
    box-shadow: inset 0 -1px 0px 0 var(--base-color-tone-b);
    position: sticky;
    top: 0;
    z-index: 20;
  }

  .preamble {
    display: grid;
    grid-template-columns: 3rem 1fr;
    grid-column-gap: 0.8rem;
    align-items: center;
    margin-top: 0.4rem;
    padding: 0 1.6rem;
    font-size: 0.85em;
    background-image: linear-gradient(45deg, rgba(pink, 0.2), rgba(orange, 0.2));
    color: var(--inverse-color-tone-a);

    p {
      margin: 0.75rem 0;
    }

    :global(.icon) {
      width: 3rem;
      height: 3rem;
      fill: var(--inverse-color-tone-b);
    }
  }

  .addon-list {
    @extend %unstyle-list;
    margin: 0.8em 0;

    li {
      border-radius: 4px;

      + li {
        margin-top: 4px;
      }

      &:nth-child(odd) {
        background-color: var(--base-color);
      }
    }
  }
</style>
