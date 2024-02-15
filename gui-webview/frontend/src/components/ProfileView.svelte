<script context="module" lang="ts">
  import * as commonmark from "commonmark";
  import ld from "lodash-es";
  import type { ComponentProps } from "svelte";
  import { getContext, onMount, setContext, unstate } from "svelte";
  import { flip } from "svelte/animate";
  import { isSameAddon } from "../addon";
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
  import { Api, ChangelogFormat, Strategy, addonToDefn } from "../api";
  import { AddonAction, ListFormat, View } from "../constants";
  import { ALERTS_KEY, type AlertsRef } from "../stores/alerts.svelte";
  import { API_KEY } from "../stores/api";
  import { PROFILES_KEY, type ProfilesRef } from "../stores/profiles.svelte";
  import AddonComponent from "./Addon.svelte";
  import AddonContextMenu from "./AddonContextMenu.svelte";
  import AddonList from "./AddonList.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import ChangelogModalContents from "./ChangelogModalContents.svelte";
  import Reconciler from "./Reconciler.svelte";
  import Rereconciler from "./Rereconciler.svelte";
  import RollbackModalContents from "./RollbackModalContents.svelte";
  import SearchOptionsModalContents from "./SearchOptionsModalContents.svelte";
  import Modal from "./modal/Modal.svelte";

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
  let { profile, isActive, statusMessage } = $props<{
    profile: string;
    isActive: boolean;
    statusMessage: string;
  }>();

  const profilesRef = getContext<ProfilesRef>(PROFILES_KEY);
  const alertsRef = getContext<AlertsRef>(ALERTS_KEY);

  const api = setContext<Api>(API_KEY, getContext<Api>(API_KEY).withProfile(profile));

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

  let searchIsDirty = $derived.by(() => {
    const fields = ["sources", "startDate", "strategies"] as const;

    return !ld.isEqual(ld.pick(searchOptions, fields), ld.pick(defaultSearchOptions, fields));
  });

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

  const countInstalled = () => {
    return addonsByView[View.Installed].reduce((val, [, , installed]) => val + +installed, 0);
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

  const removeAddons = async (addons: Addon[], keepFolders: boolean) => {
    await modifyAddons("remove", addons, { keep_folders: keepFolders });
  };

  const pinAddons = async (addons: Addon[]) => {
    await modifyAddons("pin", addons);
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
    console.debug(profile, "updating `searchOptions.fromAlias`");
    searchOptions.fromAlias = uriSchemes?.some((s) => searchTerms.startsWith(s)) ?? false;
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
    addonsByView[View.Installed];

    console.debug(profile, "updating status message");

    if (isActive) {
      if (installedIsRefreshing) {
        statusMessage = "refreshing…";
      } else if (false /* reconcileInstallationInProgress */) {
        statusMessage = "installing…";
      } else {
        statusMessage = `installed add-ons: ${countInstalled()}`;
      }
    }
  });
</script>

{#if isActive}
  <div class="addon-list-wrapper">
    {#snippet addonListNav(props)}
      <div class="addon-list-nav-wrapper">
        <AddonListNav
          bind:activeView
          bind:searchTerms
          bind:searchFilterInstalled
          {searchIsDirty}
          {installedOutdatedCount}
          isRefreshing={installedIsRefreshing}
          isModifying={installedAddonsBeingModified.length > 0}
          isSearching={searchesInProgress > 0}
          onSearch={() => search()}
          onShowSearchOptionsModal={() => showSearchOptionsModal()}
          onRefresh={() => refreshInstalled()}
          onUpdateAll={() => updateAddons(true)}
          onCycleListFormat={() => cycleDisplayedListFormat()}
          {...props}
        />
      </div>
    {/snippet}

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
            bind:searchOptions
            onRequestSearch={search}
            onRequestReset={resetSearchState}
          />
        {/if}
      </Modal>
    {/if}

    {#if activeView === View.Reconcile}
      <Reconciler {addonListNav} {modifyAddons} />
    {:else if activeView === View.ReconcileInstalled}
      <Rereconciler bind:activeView {addonListNav} {modifyAddons} />
    {:else}
      {@render addonListNav({})}

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
  @use "scss/vars";

  .addon-list-wrapper {
    @extend %stretch-vertically;
    position: relative;
    overflow-y: auto;
    -webkit-user-select: none;
    user-select: none;
  }

  .addon-list-nav-wrapper {
    @extend %blur-background;
    background-color: var(--base-color-tone-a-alpha-85);
    box-shadow: inset 0 -1px 0px 0 var(--base-color-tone-b);
    position: sticky;
    top: 0;
    z-index: 20;
    padding: 0 0.8em;
  }
</style>
