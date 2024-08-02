<script context="module" lang="ts">
  import * as commonmark from "commonmark";
  import ld from "lodash-es";
  import type { ComponentProps, Snippet } from "svelte";
  import { getContext, onMount, setContext } from "svelte";
  import { flip } from "svelte/animate";
  import { isSameAddon } from "../addon";
  import {
    ReconciliationStage,
    type Addon,
    type AnyResult,
    type CatalogueEntry,
    type Defn,
    type ErrorResult,
    type Source,
    type Strategies,
    type SuccessResult,
  } from "../api";
  import { ChangelogFormat, Strategy, addonToDefn } from "../api";
  import { AddonAction, ListFormat, View, type TogaSimulateKeypressAction } from "../constants";
  import { ALERTS_KEY, type AlertsRef } from "../stores/alerts.svelte";
  import { API_KEY, Api } from "../stores/api.svelte";
  import { PROFILES_KEY, type ProfilesRef } from "../stores/profiles.svelte";
  import AddonComponent from "./Addon.svelte";
  import AddonContextMenu from "./AddonContextMenu.svelte";
  import AddonList from "./AddonList.svelte";
  import ChangelogModalContents from "./ChangelogModalContents.svelte";
  import Reconciler from "./Reconciler.svelte";
  import Rereconciler from "./Rereconciler.svelte";
  import RollbackModalContents from "./RollbackModalContents.svelte";
  import SearchOptionsModalContents from "./SearchOptionsModalContents.svelte";
  import Modal from "./modal/Modal.svelte";
  import SvgIcon from "./SvgIcon.svelte";
  import { faExchange, faFilter, faSlidersH, faThList } from "@fortawesome/free-solid-svg-icons";
  import Spinner from "./Spinner.svelte";

  type AddonTriplet = readonly [addon: Addon, otherAddon: Addon, isInstalled: boolean];

  const createAddonToken = (value: Addon | Defn) =>
    [value.source, (value as Addon).id || (value as Defn).alias].join(":");

  const tripletWithAddonToken = ([addon, ...rest]: AddonTriplet) =>
    [addon, ...rest, createAddonToken(addon)] as const;

  export type SearchStrategies = {
    [K in keyof Strategies]: NonNullable<
      Strategies[K] extends boolean | null ? boolean : Strategies[K]
    >;
  };

  const defaultSearchOptions: {
    limit: number;
    sources: string[];
    startDate: string | null;
    strategies: SearchStrategies;
  } = {
    limit: 20,
    sources: [],
    startDate: null,
    strategies: {
      [Strategy.AnyFlavour]: false,
      [Strategy.AnyReleaseType]: false,
      [Strategy.VersionEq]: "",
    },
  };
  const searchDiffFields = ["sources", "startDate", "strategies"] as const;

  export type SearchOptions = typeof defaultSearchOptions;

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
  let {
    profile,
    isActive,
    statusMessage = $bindable(),
  }: {
    profile: string;
    isActive: boolean;
    statusMessage: string;
  } = $props();

  const profilesRef = getContext<ProfilesRef>(PROFILES_KEY);
  const alertsRef = getContext<AlertsRef>(ALERTS_KEY);

  const api = setContext(API_KEY, new Api(getContext(API_KEY), profile, alertsRef));

  const config = $derived(profilesRef.value[profile]);

  let sources = $state.frozen<{
    [source: string]: Source;
  }>({});
  let uriSchemes = $state<string[]>();

  let activeView = $state(View.Installed);
  let installedListFormat = $state(ListFormat.Compact);
  let searchListFormat = $state(ListFormat.Expanded);

  let filteredCatalogueEntries = $state<CatalogueEntry[]>([]);
  let addonsFromSearch = $state<Addon[]>([]);
  let installedAddonsBeingModified = $state<string[]>([]);

  const addonsByView = $state<
    Record<View.Installed | View.FilterInstalled | View.Search, AddonTriplet[]>
  >({
    [View.Installed]: [],
    [View.FilterInstalled]: [],
    [View.Search]: [],
  });

  let installedOutdatedCount = $derived(
    addonsByView[View.Installed].reduce(
      (val, [thisAddon, otherAddon]) =>
        val + (otherAddon && thisAddon.version !== otherAddon.version ? 1 : 0),
      0,
    ),
  );

  let addonDownloadProgress = $state.frozen<{
    [token: string]: number;
  }>({});

  let searchTerms = $state("");
  let searchFilterInstalled = $state(false);
  let searchOptions = $state(ld.cloneDeep(defaultSearchOptions));

  let searchIsDirty = $derived(
    !ld.isEqual(
      ld.pick(searchOptions, searchDiffFields),
      ld.pick(defaultSearchOptions, searchDiffFields),
    ),
  );
  let searchIsFromAlias = $derived(uriSchemes?.some((s) => searchTerms.startsWith(s)) ?? false);

  let installedIsRefreshing = $state(false);
  let searchesInProgress = $state(0);

  let modal = $state<
    | { id: "changelog"; dynamicProps: ComponentProps<ChangelogModalContents> }
    | { id: "rollback"; dynamicProps: ComponentProps<RollbackModalContents> }
    | { id: "searchOptions" }
  >();

  let addonContextMenu = $state<AddonContextMenu>();

  const alertAddonOpFailed = (method: string, combinedResult: (readonly [Addon, AnyResult])[]) => {
    alertsRef.value[profile] = [
      ...combinedResult
        .filter((c): c is [Addon, ErrorResult] => c[1].status !== "success")
        .map(([a, r]) => ({
          heading: `failed to ${method} ${a.name} (${createAddonToken(a)})`,
          message: r.message,
        })),
      ...(alertsRef.value[profile] ?? []),
    ];
  };

  const regenerateFilteredAddons = () => {
    return addonsByView[View.Installed].filter(([a]) =>
      filteredCatalogueEntries.some((e) => a.source === e.source && a.id === e.id),
    );
  };

  const regenerateSearchAddons = () => {
    return addonsFromSearch.map((addon) => {
      const installedAddonTriplet = addonsByView[View.Installed].find(([a]) =>
        isSameAddon(a, addon),
      );
      if (installedAddonTriplet) {
        const [installedAddon, , isInstalled] = installedAddonTriplet;
        return [installedAddon, addon, isInstalled] as const;
      }
      return [addon, addon, false] as const;
    });
  };

  const withDownloadProgress = async <T,>(promise: Promise<T>, pollingInterval: number) => {
    const ticker = setInterval(async () => {
      const downloadProgress = await api.getDownloadProgress();
      addonDownloadProgress = Object.fromEntries(
        downloadProgress.map(({ defn, progress }) => [createAddonToken(defn), progress]),
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
    extraParams: { [key: string]: unknown } = {},
  ) => {
    const addonTokens = addons.map(createAddonToken);
    installedAddonsBeingModified = [...installedAddonsBeingModified, ...addonTokens];

    try {
      const modifyResults = await withDownloadProgress(
        api.modifyAddons(method, addons.map(addonToDefn), extraParams),
        1000,
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
        addons.map((a, i) => [a, modifyResults[i]]),
      );
    } finally {
      installedAddonsBeingModified = ld.difference(installedAddonsBeingModified, addonTokens);
    }
  };

  const installAddons = async (addons: Addon[], replace = false) => {
    await modifyAddons("install", addons, { replace });
  };

  const updateAddons = async (addons: Addon[] | true) => {
    if (addons === true) {
      const outdatedAddons = addonsByView[View.Installed]
        .filter(
          ([{ version: thisVersion }, { version: otherVersion }]) => thisVersion !== otherVersion,
        )
        .map(([, addon]) => addon);
      await modifyAddons("update", outdatedAddons);
    } else {
      await modifyAddons("update", addons);
    }
  };

  const removeAddons = async (addons: Addon[], keepFolders = false) => {
    await modifyAddons("remove", addons, { keep_folders: keepFolders });
  };

  const pinAddons = async (addons: Addon[]) => {
    await modifyAddons("pin", addons);
  };

  const reconcileAddons = async (
    stage: ReconciliationStage,
    stages: ReconciliationStage[],
    selections: Addon[],
    recursive?: boolean,
  ): Promise<ReconciliationStage | undefined> => {
    await installAddons(selections.filter(Boolean), true);

    const nextStage = stages[stages.indexOf(stage) + 1];
    if (nextStage) {
      if (recursive) {
        const nextSelections = (await api.reconcile(stage))
          .filter((r) => r.matches.length)
          .map(({ matches: [addon] }) => addon);
        return await reconcileAddons(nextStage, stages, nextSelections, recursive);
      }
      return nextStage;
    }
  };

  const rereconcileAddons = async (addonPairs: (readonly [Addon, Addon])[]) => {
    await installAddons(addonPairs.map(([, a]) => a));
    await removeAddons(addonPairs.map(([a]) => a));

    activeView = View.Installed;
  };

  const search = async () => {
    searchesInProgress++;

    try {
      const searchTermsSnapshot = searchTerms;

      if (searchTermsSnapshot) {
        let results: AnyResult[];

        const condensedStrategies = Object.fromEntries(
          Object.entries(searchOptions.strategies).map(([k, v]) => [k, v || null]),
        ) as Strategies;

        if (searchIsFromAlias) {
          let source = "",
            alias = searchTermsSnapshot;

          const colonIndex = searchTermsSnapshot.indexOf(":");
          if (colonIndex !== -1) {
            const sourceCandidate = searchTermsSnapshot.slice(0, colonIndex);
            if (sourceCandidate in sources) {
              source = sourceCandidate;
              alias = searchTermsSnapshot.slice(colonIndex + 1);
            }
          }

          results = await api.resolve([
            {
              source,
              alias,
              strategies: condensedStrategies,
            },
          ]);
        } else {
          const catalogueEntries = await api.search(
            searchTermsSnapshot,
            searchOptions.limit,
            searchOptions.sources,
            searchOptions.startDate,
            searchFilterInstalled,
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
          results = await api.resolve(defns);
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
        const installedAddons = await api.list();
        if (flash) {
          addonsByView[View.Installed] = installedAddons.map((a) => [a, a, true]);
        }
        const resolveResults = await api.resolve(installedAddons.map(addonToDefn));
        const addonsToResults = installedAddons.map((a, i) => [a, resolveResults[i]] as const);
        addonsByView[View.Installed] = ld.sortBy(
          addonsToResults.map(([thisAddon, result]) => [
            thisAddon,
            result.status === "success" ? result.addon : thisAddon,
            true,
          ]),
          // Haul outdated add-ons to the top
          ([thisAddon, { version: otherVersion }]) => [
            thisAddon.version === otherVersion,
            thisAddon.name.toLowerCase(),
          ],
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
    const changelog = await api.getChangelog(addon.source, addon.changelog_url);
    modal = {
      id: "changelog",
      dynamicProps: htmlify(changelog, sources[addon.source].changelog_format),
    };
  };

  const showRollbackModal = (addon: Addon) => {
    modal = {
      id: "rollback",
      dynamicProps: { addon, onRequestRollback: (addon) => updateAddons([addon]) },
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
    { clientX: x, clientY: y }: MouseEvent,
  ) => {
    addonContextMenu?.show(
      { x, y },
      {
        addon,
        installed,
        supportsRollback: supportsRollback(addon),
      },
    );
  };

  const handleAddonContextMenuSelection = ({
    addon,
    action,
  }: {
    addon: Addon;
    action: AddonAction;
  }) => {
    switch (action) {
      case AddonAction.VisitHomepage:
        api.openUrl(addon.url);
        break;

      case AddonAction.ViewChangelog:
        showChangelogModal(addon);
        break;

      case AddonAction.RevealFolder: {
        const {
          folders: [{ name: folderName }],
        } = addon;
        api.revealFolder([config.addon_dir, folderName]);

        break;
      }

      case AddonAction.Resolve: {
        searchOptions = {
          ...ld.cloneDeep(defaultSearchOptions),
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
        const pinnedAddon = ld.merge(addon);
        pinnedAddon.options.version_eq = action === AddonAction.Pin;
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

  const supportsRollback = (addon: Addon) =>
    !!sources[addon.source]?.strategies.includes(Strategy.VersionEq);

  const resetSearchState = () => {
    searchOptions = ld.cloneDeep(defaultSearchOptions);
  };

  const cycleDisplayedListFormat = () => {
    if (activeView === View.Installed || activeView === View.FilterInstalled) {
      installedListFormat = cycleListFormat(installedListFormat);
    } else if (activeView === View.Search) {
      searchListFormat = cycleListFormat(searchListFormat);
    }
  };

  let searchBox = $state<HTMLInputElement>();

  const handleKeypress = ({
    detail: { action },
  }: CustomEvent<{ action: TogaSimulateKeypressAction }>) => {
    if (!isActive) {
      return;
    }

    switch (action) {
      case "activateViewInstalled":
        activeView = View.Installed;
        break;
      case "activateViewReconcile":
        activeView = View.Reconcile;
        break;
      case "activateViewSearch":
        activeView = View.Search;
        searchBox?.focus();
        break;
      case "toggleSearchFilter":
        searchFilterInstalled = !searchFilterInstalled;
        if (searchFilterInstalled) {
          searchBox?.focus();
        }
        break;
    }
  };

  onMount(async () => {
    sources = await api.listSources();
    uriSchemes = [...Object.keys(sources), "http", "https"].map((s) => `${s}:`);
    await refreshInstalled(true);
    // Switch over to reconciliation if no add-ons are installed
    if (!addonsByView[View.Installed].length) {
      activeView = View.Reconcile;
    }
  });

  $effect(() => {
    if (activeView !== View.Search && searchTerms === "") {
      console.debug(profile, "resetting search state");
      resetSearchState();
    }
  });

  $effect(() => {
    searchFilterInstalled;

    console.debug(profile, "filter status changed, resetting search state");
    resetSearchState();
  });

  $effect(() => {
    if (searchOptions.startDate === "") {
      console.debug(profile, "resetting `searchOptions.startDate`");
      searchOptions.startDate = null;
    }
  });

  $effect(() => {
    addonsByView[View.Installed], filteredCatalogueEntries;

    addonsByView[View.FilterInstalled] = regenerateFilteredAddons();
  });

  $effect(() => {
    addonsByView[View.Installed], addonsFromSearch;

    addonsByView[View.Search] = regenerateSearchAddons();
  });

  $effect(() => {
    if (!isActive) {
      return;
    }

    console.debug(profile, "updating status message");

    if (installedIsRefreshing) {
      statusMessage = "refreshing…";
    } else {
      statusMessage = `installed add-ons: ${addonsByView[View.Installed].reduce(
        (val, [, , installed]) => val + +installed,
        0,
      )}`;
    }
  });
</script>

<svelte:window ontogaSimulateKeypress={handleKeypress} />

{#snippet profileNav(navMiddle?: Snippet, navEnd?: Snippet)}
  <div class="profile-nav-wrapper">
    <nav class="profile-nav">
      <div>
        <menu class="control-set">
          <li class="segmented-control">
            <input
              class="control"
              type="radio"
              id="__radio-installed"
              value={View.Installed}
              bind:group={activeView}
            />
            <label class="control" for="__radio-installed">installed</label>
          </li>

          <li class="segmented-control">
            <input
              class="control"
              type="radio"
              id="__radio-unreconciled"
              value={View.Reconcile}
              bind:group={activeView}
            />
            <label class="control" for="__radio-unreconciled">unreconciled</label>
          </li>

          {#if activeView === View.Installed || activeView === View.ReconcileInstalled}
            <li>
              <input
                class="control"
                id="__radio-reconcile-installed"
                type="radio"
                value={View.ReconcileInstalled}
                bind:group={activeView}
              />
              <label
                class="control"
                for="__radio-reconcile-installed"
                aria-label="change add-on sources"
                title="change add-on sources"
              >
                <SvgIcon icon={faExchange} />
              </label>
            </li>
          {/if}

          {#if activeView !== View.Reconcile && activeView !== View.ReconcileInstalled}
            <li>
              <button
                class="control"
                aria-label="condense/expand add-on cells"
                title="condense/expand add-on cells"
                onclick={cycleDisplayedListFormat}
              >
                <SvgIcon icon={faThList} />
              </button>
            </li>
          {/if}
        </menu>
      </div>

      <div>
        {@render navMiddle?.()}
      </div>

      <div>
        {@render navEnd?.()}
      </div>
    </nav>
  </div>
{/snippet}

{#snippet profileNavMiddle()}
  <menu class="control-set">
    <li>
      <input
        class="control"
        id="__search-installed"
        type="checkbox"
        bind:checked={searchFilterInstalled}
      />
      <label
        class="control"
        for="__search-installed"
        aria-label="search installed add-ons"
        title="search installed add-ons"
      >
        <SvgIcon icon={faFilter} />
      </label>
    </li>
    <li>
      <!-- Not type="search" because cursor jumps to end in Safari -->
      <input
        class="control search-control"
        type="text"
        placeholder="search"
        bind:this={searchBox}
        bind:value={searchTerms}
        onkeydown={(e) => e.key === "Enter" && search()}
      />
    </li>
  </menu>

  {#if searchesInProgress > 0}
    <Spinner />
  {/if}
{/snippet}

{#snippet profileNavEnd()}
  <menu class="control-set">
    {#if activeView === View.Installed}
      <li>
        <button
          class="control"
          disabled={installedIsRefreshing}
          onclick={() => refreshInstalled()}
        >
          refresh
        </button>
      </li>
      <li>
        <button
          class="control"
          disabled={installedAddonsBeingModified.length > 0 ||
            installedIsRefreshing ||
            !installedOutdatedCount}
          onclick={() => updateAddons(true)}
        >
          {installedOutdatedCount ? `update ${installedOutdatedCount}` : "no updates"}
        </button>
      </li>
    {:else}
      <li>
        <button
          class="control search-options-control"
          class:dirty={searchIsDirty}
          aria-label="show search options"
          onclick={showSearchOptionsModal}
        >
          <SvgIcon icon={faSlidersH} />
        </button>
      </li>
    {/if}
  </menu>
{/snippet}

{#if isActive}
  <div class="addon-list-wrapper">
    <AddonContextMenu
      bind:this={addonContextMenu}
      onSelectItem={handleAddonContextMenuSelection}
    />

    {#if modal}
      <Modal onHide={resetModal}>
        {#if modal.id === "changelog"}
          <ChangelogModalContents {...modal.dynamicProps} />
        {:else if modal.id === "rollback"}
          <RollbackModalContents {...modal.dynamicProps} />
        {:else if modal.id === "searchOptions"}
          <SearchOptionsModalContents
            flavour={config.game_flavour}
            {sources}
            {searchFilterInstalled}
            {searchIsFromAlias}
            bind:searchOptions
            onRequestSearch={search}
            onRequestReset={resetSearchState}
          />
        {/if}
      </Modal>
    {/if}

    {#if activeView === View.Reconcile}
      <Reconciler {profileNav} onReconcile={reconcileAddons} />
    {:else if activeView === View.ReconcileInstalled}
      <Rereconciler {profileNav} onRereconcile={rereconcileAddons} />
    {:else}
      {@render profileNav(profileNavMiddle, profileNavEnd)}

      {#key activeView}
        <AddonList>
          {#each addonsByView[activeView].map(tripletWithAddonToken) as [addon, otherAddon, isInstalled, token] (token)}
            <li animate:flip={{ duration: 250 }}>
              <AddonComponent
                {addon}
                {otherAddon}
                {isInstalled}
                beingModified={installedAddonsBeingModified.includes(token)}
                format={activeView === View.Search ? searchListFormat : installedListFormat}
                isRefreshing={installedIsRefreshing}
                downloadProgress={addonDownloadProgress[token] || 0}
                onInstall={() => installAddons([otherAddon])}
                onUpdate={() => updateAddons([otherAddon])}
                onRemove={() => removeAddons([addon], false)}
                onShowChangelogModal={() => showChangelogModal(otherAddon)}
                onShowAddonContextMenu={(e) =>
                  showAddonContextMenu(isInstalled ? addon : otherAddon, isInstalled, e)}
              />
            </li>
          {/each}
        </AddonList>
      {/key}
    {/if}
  </div>
{/if}

<style lang="scss">
  @use "sass:math";

  @use "scss/vars";

  $line-height: 1.875em;
  $middle-border-radius: math.div($line-height, 6);
  $edge-border-radius: math.div($line-height, 4);

  .addon-list-wrapper {
    @extend %stretch-vertically;
    position: relative;
    overflow-y: auto;
    -webkit-user-select: none;
    user-select: none;
  }

  .profile-nav-wrapper {
    @extend %blur-background;
    background-color: var(--base-color-tone-a-alpha-85);
    box-shadow: inset 0 -1px 0px 0 var(--base-color-tone-b);
    position: sticky;
    top: 0;
    z-index: 20;
    padding: 0 0.8em;
  }

  .profile-nav {
    @extend %nav-grid;
    grid-template-columns: repeat(3, 1fr);
    height: 3rem;

    > div {
      display: flex;
      align-items: center;
    }
  }

  :global(.profile-nav menu) {
    @extend %unstyle-list;
    font-weight: 500;
  }

  :global(.profile-nav .control-set) {
    display: flex;
    align-items: center;
    font-size: 0.85em;

    li {
      &:not(:first-child) {
        margin-left: 4px;
      }

      &.segmented-control {
        ~ .segmented-control {
          margin-left: -1px;
        }
      }

      &:first-child .control {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-child .control {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }
    }
  }

  :global(.profile-nav .control) {
    display: block;
    min-width: min-content;
    border: 0;
    transition: all 0.2s;
    line-height: $line-height;
    margin: 0;
    padding: 0 0.7em;
    border-radius: $middle-border-radius;
    white-space: nowrap;

    &:disabled {
      opacity: 0.5;
    }

    &:hover:not(:disabled) {
      background-color: var(--inverse-color-alpha-05);
    }

    &:focus {
      background-color: var(--inverse-color-alpha-10);
    }

    &[type="checkbox"],
    &[type="radio"] {
      position: absolute;
      opacity: 0;

      &:checked + label {
        background-color: var(--inverse-color-tone-b) !important;
        color: var(--base-color);

        :global(.icon) {
          fill: var(--base-color);
        }
      }

      &:disabled + label {
        opacity: 0.5;
      }

      &:focus + label {
        background-color: var(--inverse-color-alpha-10);
      }
    }

    :global(.icon) {
      height: 1rem;
      width: 1rem;
      vertical-align: text-bottom;
      fill: var(--inverse-color-tone-b);
    }

    &.search-control {
      border-top-right-radius: $edge-border-radius;
      border-bottom-right-radius: $edge-border-radius;
      box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-10);
      font-size: 1rem;

      &,
      &::-webkit-search-cancel-button {
        -webkit-appearance: none;
        appearance: none;
      }

      &:not(:focus) {
        text-align: center;
      }
    }

    &.search-options-control.dirty {
      @include vars.striped-background(-45deg, rgba(salmon, 0.5));
    }
  }
</style>
