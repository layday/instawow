<script context="module" lang="ts">
  import { faQuestion } from "@fortawesome/free-solid-svg-icons";
  import { JSONRPCError } from "@open-rpc/client-js";
  import * as commonmark from "commonmark";
  import lodash from "lodash";
  import { onMount } from "svelte";
  import { flip } from "svelte/animate";
  import { fade } from "svelte/transition";
  import type {
    Addon,
    AddonWithMeta,
    AnyResult,
    CatalogueEntry,
    Defn,
    ErrorResult,
    Source,
    SuccessResult,
  } from "../api";
  import { addonToDefn, Api, ChangelogFormat, ReconciliationStage, Strategy } from "../api";
  import { ListFormat, View } from "../constants";
  import type { RequestObject } from "../ipc";
  import { api, profiles } from "../store";
  import AddonComponent from "./Addon.svelte";
  import AddonContextMenu from "./AddonContextMenu.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import type { Alert } from "./Alerts.svelte";
  import Alerts from "./Alerts.svelte";
  import ChangelogModal from "./ChangelogModal.svelte";
  import RollbackModal from "./RollbackModal.svelte";
  import SearchOptionsModal from "./SearchOptionsModal.svelte";
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

  const createAddonToken = (value: Addon | Defn) =>
    [value.source, (value as Addon).id || (value as Defn).alias].join(":");

  const attachTokentoAddon = ([addon, otherAddon]: AddonTuple): [AddonWithMeta, Addon, string] => [
    addon,
    otherAddon,
    createAddonToken(addon),
  ];

  const isSameAddon = (thisAddon: Addon, otherAddon: Addon) =>
    thisAddon.source === otherAddon.source && thisAddon.id === otherAddon.id;

  const markAddonInstalled = (addon: Addon, installed: boolean = true): AddonWithMeta => ({
    __installed__: installed,
    ...addon,
  });

  const reconcileStages = Object.values(ReconciliationStage);

  const defaultSearchState: {
    searchTerms: string;
    searchFilterInstalled: boolean;
    searchFromAlias: boolean;
    searchSources: string[];
    searchStrategy: Strategy;
    searchVersion: string;
    searchStartDate: string | null;
    searchLimit: number;
  } = {
    searchTerms: "",
    searchFilterInstalled: false,
    searchFromAlias: false,
    searchSources: [],
    searchStrategy: Strategy.default,
    searchVersion: "",
    searchStartDate: null,
    searchLimit: 20,
  };

  const htmlify = (changelog: string, format: ChangelogFormat): [boolean, string] => {
    if (format === ChangelogFormat.markdown) {
      return [
        true,
        new commonmark.HtmlRenderer().render(new commonmark.Parser().parse(changelog)),
      ];
    } else {
      return [format === ChangelogFormat.html, changelog];
    }
  };

  const cycleListFormat = (currentFormat: ListFormat) => {
    const listFormatKey = ListFormat[currentFormat + 1] as keyof typeof ListFormat;
    return ListFormat[listFormatKey] || ListFormat.Dense;
  };
</script>

<script lang="ts">
  export let profile: string, isActive: boolean, statusMessage: string;

  class AlertOnErrorApi extends Api {
    async request(requestObject: RequestObject) {
      try {
        return await super.request(requestObject);
      } catch (error) {
        alertForJsonRpcError(error);
        throw error;
      }
    }
  }

  const config = $profiles.get(profile)!;
  const profileApi = $api.withProfile(profile, AlertOnErrorApi);

  let sources: { [source: string]: Source } = {};
  let uriSchemes: string[];

  let activeView: View = View.Installed;
  let installedListFormat = ListFormat.Compact;
  let searchListFormat = ListFormat.Expanded;

  let addons__Installed: AddonTuple[] = [];
  let filteredCatalogueEntries: CatalogueEntry[] = [];
  let addons__FilterInstalled: AddonTuple[] = [];
  let addonsFromSearch: Addon[] = [];
  let addons__Search: AddonTuple[] = [];
  let installedOutdatedCount: number;
  let installedAddonsBeingModified: string[] = [];

  let addonDownloadProgress: { [token: string]: number } = {};

  let {
    searchTerms,
    searchFilterInstalled,
    searchFromAlias,
    searchSources,
    searchStrategy,
    searchVersion,
    searchStartDate,
    searchLimit,
  } = defaultSearchState;
  let searchIsDirty = false;

  let alerts: Alert[] = [];

  let reconcileStage: ReconciliationStage = reconcileStages[0];
  let reconcileSelections: Addon[];

  let reconcileInstalledAddons: Addon[];
  let reconcileInstalledSelections: Addon[];

  let installedIsRefreshing = false;
  let searchesInProgress = 0;
  let reconcileInstallationInProgress = false;

  let changelogModal = false;
  let changelogModalProps: { changelog: string; renderAsHtml: boolean };
  let rollbackModal = false;
  let rollbackModalProps: { addon: Addon };
  let searchOptionsModal = false;

  let addonContextMenu = false;
  let addonContextMenuProps: {
    addon: Addon;
    installed: boolean;
    supportsRollback: boolean;
    eventX: number;
    eventY: number;
  };

  const alertAddonOpFailed = (method: string, combinedResult: (readonly [Addon, AnyResult])[]) => {
    const newAlerts = combinedResult
      .filter((c): c is [Addon, ErrorResult] => c[1].status !== "success")
      .map(([a, r]) => ({
        heading: `failed to ${method} ${a.name} (${createAddonToken(a)})`,
        message: r.message,
      }));
    alerts = [...newAlerts, ...alerts];
  };

  const alertForJsonRpcError = (error: any) => {
    if (error instanceof JSONRPCError) {
      const newAlert: Alert = {
        heading: error.message,
        message: (error.data as any).traceback_exception.filter(Boolean).slice(-1),
      };
      alerts = [newAlert, ...alerts];
    }
  };

  const countUpdates = () => {
    installedOutdatedCount = addons__Installed.reduce(
      (val, [thisAddon, otherAddon]) =>
        val + (otherAddon && thisAddon.version !== otherAddon.version ? 1 : 0),
      0
    );
  };

  const regenerateFilteredAddons = () => {
    addons__FilterInstalled = addons__Installed.filter(([a]) =>
      filteredCatalogueEntries.some((e) => a.source === e.source && a.id === e.id)
    );
  };

  const regenerateSearchAddons = () => {
    addons__Search = addonsFromSearch.map((addon) => {
      const installedAddon = addons__Installed.find((installedAddon) =>
        isSameAddon(installedAddon[0], addon)
      );
      return [installedAddon?.[0] || markAddonInstalled(addon, false), addon] as const;
    });
  };

  const scheduleDownloadProgressPolling = (delay: number) => {
    const ticker = setInterval(async () => {
      const downloadProgress = await profileApi.getDownloadProgress();
      addonDownloadProgress = lodash.fromPairs(
        downloadProgress.map(({ defn, progress }) => [createAddonToken(defn), progress])
      );
    }, delay);

    return () => clearInterval(ticker);
  };

  const modifyAddons = async (
    method: "install" | "update" | "remove" | "pin",
    addons: Addon[],
    extraParams: { [key: string]: any } = {}
  ) => {
    const addonTolens = addons.map(createAddonToken);
    installedAddonsBeingModified = [...installedAddonsBeingModified, ...addonTolens];
    const cancelDownloadProgessPolling = scheduleDownloadProgressPolling(1000);

    try {
      const modifyResults = await profileApi.modifyAddons(
        method,
        addons.map(addonToDefn),
        extraParams
      );
      const modifiedAddons = modifyResults
        .filter((result): result is SuccessResult => result.status === "success")
        .map(({ addon }) => addon);
      if (modifiedAddons.length) {
        const installedAddons = [...addons__Installed];
        // Reversing `modifiedAddons` for new add-ons to be prepended in alphabetical order
        for (const addon of [...modifiedAddons].reverse()) {
          const newAddon = [markAddonInstalled(addon, method !== "remove"), addon] as const;
          const index = addons__Installed.findIndex((value) => isSameAddon(value[0], addon));
          if (index === -1) {
            installedAddons.unshift(newAddon);
          } else {
            installedAddons[index] = newAddon;
          }
        }
        addons__Installed = installedAddons;
        regenerateFilteredAddons();
        regenerateSearchAddons();
      }
      alertAddonOpFailed(
        method,
        addons.map((a, i) => [a, modifyResults[i]])
      );
    } finally {
      try {
        cancelDownloadProgessPolling();
      } finally {
        installedAddonsBeingModified = lodash.difference(
          installedAddonsBeingModified,
          addonTolens
        );
      }
    }
  };

  const installAddons = async (addons: Addon[], replace = false) => {
    await modifyAddons("install", addons, { replace: replace });
  };

  const updateAddons = async (addons: Addon[] | true) => {
    if (addons === true) {
      const outdatedAddons = addons__Installed
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
    return uriSchemes.some((s) => searchTerms.startsWith(s));
  };

  const search = async () => {
    searchesInProgress++;

    try {
      const searchTermsSnapshot = searchTerms;

      if (searchTermsSnapshot) {
        let results: AnyResult[];

        if (searchFromAlias) {
          results = await profileApi.resolve([
            {
              source: "*",
              alias: searchTermsSnapshot,
              strategy: searchStrategy,
              version: searchVersion,
            },
          ]);
        } else {
          const catalogueEntries = await profileApi.search(
            searchTermsSnapshot,
            searchLimit,
            searchSources,
            searchStartDate,
            searchFilterInstalled
          );

          if (searchTermsSnapshot !== searchTerms) {
            return;
          }

          if (searchFilterInstalled) {
            filteredCatalogueEntries = catalogueEntries;
            regenerateFilteredAddons();
            activeView = View.FilterInstalled;
            return;
          }

          const defns = catalogueEntries.map((e) => ({
            source: e.source,
            alias: e.id,
            strategy: searchStrategy,
            version: searchVersion,
          }));
          results = await profileApi.resolve(defns);
        }

        if (searchTermsSnapshot !== searchTerms) {
          return;
        }

        addonsFromSearch = results
          .filter((result): result is SuccessResult => result.status === "success")
          .map(({ addon }) => addon);
        regenerateSearchAddons();
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
        const installedAddons = (await profileApi.list()).map((addon) =>
          markAddonInstalled(addon)
        );
        if (flash) {
          addons__Installed = installedAddons.map((a) => [a, a]);
        }
        const resolveResults = await profileApi.resolve(installedAddons.map(addonToDefn));
        const addonsToResults = installedAddons.map((a, i) => [a, resolveResults[i]] as const);
        addons__Installed = lodash.sortBy(
          addonsToResults.map(([thisAddon, result]) => [
            thisAddon,
            result.status === "success" ? result.addon : thisAddon,
          ]),
          // Haul outdated add-ons up to the top
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
    const changelogFormat = sources[addon.source].changelog_format;
    const changelog = await profileApi.getChangelog(addon.changelog_url);
    const [renderAsHtml, changelogText] = htmlify(changelog, changelogFormat);
    changelogModalProps = {
      changelog: changelogText,
      renderAsHtml: renderAsHtml,
    };
    changelogModal = true;
  };

  const showRollbackModal = (addon: Addon) => {
    rollbackModalProps = { addon };
    rollbackModal = true;
  };

  const showAddonContextMenu = async (
    addon: Addon,
    installed: boolean,
    mouseEvent: MouseEvent
  ) => {
    addonContextMenuProps = {
      addon,
      installed,
      supportsRollback: supportsRollback(addon),
      eventX: mouseEvent.clientX,
      eventY: mouseEvent.clientY,
    };
    addonContextMenu = true;
  };

  const handleAddonContextMenuSelection = async (addon: Addon, selection: string) => {
    addonContextMenu = false;

    if (selection === "visit-home-page") {
      profileApi.openUrl(addon.url);
    } else if (selection === "view-changelog") {
      showChangelogModal(addon);
    } else if (selection === "reveal-folder") {
      profileApi.revealFolder([config.addon_dir, addon.folders[0].name]);
    } else if (selection === "resolve") {
      resetSearchState();
      [searchTerms, searchFromAlias, searchStrategy, searchVersion] = [
        createAddonToken(addon),
        true,
        addon.options.strategy,
        addon.version,
      ];
      await search();
    } else if (selection === "rollback") {
      showRollbackModal(addon);
    } else if (selection === "pin" || selection === "unpin") {
      const pinnedAddon = {
        ...addon,
        options: { strategy: selection === "pin" ? Strategy.version : Strategy.default },
      };
      await pinAddons([pinnedAddon]);
    } else if (selection === "unreconcile") {
      await removeAddons([addon], true);
    } else if (selection === "install-and-replace") {
      await installAddons([addon], true);
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

  const supportsRollback = (addon: Addon) => !!sources[addon.source]?.supports_rollback;

  const generateStatusMessage = () => {
    if (installedIsRefreshing) {
      return "refreshing…";
    } else if (reconcileInstallationInProgress) {
      return "installing…";
    } else {
      return `installed add-ons: ${addons__Installed.reduce(
        (a, [c]) => a + (c.__installed__ ? 1 : 0),
        0
      )}`;
    }
  };

  const resetSearchState = () => {
    ({
      searchFromAlias,
      searchSources,
      searchStrategy,
      searchVersion,
      searchStartDate,
      searchLimit,
    } = defaultSearchState);
  };

  const cycleDisplayedListFormat = () => {
    if (activeView === View.Installed || activeView === View.FilterInstalled) {
      installedListFormat = cycleListFormat(installedListFormat);
    } else if (activeView === View.Search) {
      searchListFormat = cycleListFormat(searchListFormat);
    }
  };

  onMount(async () => {
    const apiSources = await profileApi.listSources();
    sources = lodash.fromPairs(apiSources.map((s) => [s.source, s]));
    uriSchemes = [...apiSources.map((s) => s.source), "http", "https"].map((s) => `${s}:`);
    await refreshInstalled(true);
    // Switch over to reconciliation if no add-ons are installed
    if (!addons__Installed.length) {
      activeView = View.Reconcile;
    }
  });

  $: activeView !== View.Search &&
    searchTerms === "" &&
    (console.debug(profile, "resetting search state"), resetSearchState());
  $: {
    searchFilterInstalled;
    console.debug(profile, "filter status changed, resetting search state");
    resetSearchState();
  }
  $: searchStartDate === "" &&
    (searchStartDate = (console.debug(profile, "resetting `searchStartDate`"), null));
  $: searchIsDirty = [
    [searchSources, defaultSearchState.searchSources],
    [searchStartDate, defaultSearchState.searchStartDate],
    [searchStrategy, defaultSearchState.searchStrategy],
  ].some(([a, b]) => !lodash.isEqual(a, b));
  $: searchTerms &&
    (searchFromAlias =
      (console.debug(profile, "updating `searchFromAlias`"), isSearchFromAlias()));
  $: addons =
    activeView === View.Search
      ? addons__Search
      : activeView === View.FilterInstalled
      ? addons__FilterInstalled
      : addons__Installed;
  $: activeView === View.Reconcile && (reconcileStage = reconcileStages[0]);
  $: addons__Installed && (console.debug(profile, "recounting updates"), countUpdates());
  $: isActive &&
    (addons__Installed || reconcileInstallationInProgress || installedIsRefreshing) &&
    (statusMessage = generateStatusMessage());
</script>

{#if isActive}
  <div class="addon-list-wrapper">
    <div class="addon-list-nav-wrapper">
      <AddonListNav
        on:requestSearch={() => search()}
        on:requestShowSearchOptionsModal={() => (searchOptionsModal = true)}
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
        isRefreshing={installedIsRefreshing}
        isModifying={installedAddonsBeingModified.length > 0}
        isSearching={searchesInProgress > 0}
      />
    </div>
    <Alerts bind:alerts />
    {#if addonContextMenu}
      <AddonContextMenu
        bind:show={addonContextMenu}
        {...addonContextMenuProps}
        on:requestHandleContextMenuSelection={(e) => {
          const { addon, selection } = e.detail;
          handleAddonContextMenuSelection(addon, selection);
        }}
      />
    {/if}
    {#if changelogModal}
      <ChangelogModal bind:show={changelogModal} {...changelogModalProps} />
    {/if}
    {#if rollbackModal}
      <RollbackModal
        on:requestRollback={(event) => updateAddons([event.detail])}
        bind:show={rollbackModal}
        {...rollbackModalProps}
      />
    {/if}
    {#if searchOptionsModal}
      <SearchOptionsModal
        flavour={config.game_flavour}
        sources={Object.values(sources)}
        {searchFilterInstalled}
        on:requestSearch={() => search()}
        on:requestReset={() => resetSearchState()}
        bind:show={searchOptionsModal}
        bind:searchSources
        bind:searchFromAlias
        bind:searchStartDate
        bind:searchStrategy
        bind:searchVersion
        bind:searchLimit
      />
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
      <ul class="addon-list">
        {#each addons.map(attachTokentoAddon) as [addon, otherAddon, token] (token)}
          <li animate:flip={{ duration: 200 }}>
            <AddonComponent
              on:requestInstall={() => installAddons([otherAddon])}
              on:requestUpdate={() => updateAddons([otherAddon])}
              on:requestRemove={() => removeAddons([addon], false)}
              on:requestShowChangelogModal={() => showChangelogModal(otherAddon)}
              on:requestShowAddonInstalledContextMenu={(e) =>
                showAddonContextMenu(addon, true, e.detail)}
              on:requestShowAddonNotInstalledContextMenu={(e) =>
                showAddonContextMenu(otherAddon, false, e.detail)}
              {addon}
              {otherAddon}
              beingModified={installedAddonsBeingModified.includes(token)}
              format={activeView === View.Search ? searchListFormat : installedListFormat}
              isRefreshing={installedIsRefreshing}
              downloadProgress={addonDownloadProgress[token] || 0}
            />
          </li>
        {/each}
      </ul>
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
    grid-column-gap: 0.5rem;
    align-items: center;
    padding: 0 0.8rem;
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
