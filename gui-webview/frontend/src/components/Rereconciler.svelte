<script lang="ts">
  import { getContext, type ComponentProps, type Snippet } from "svelte";
  import { isSameAddon } from "../addon";
  import { type Addon } from "../api";
  import { View } from "../constants";
  import { API_KEY, type Api } from "../stores/api";
  import AddonList from "./AddonList.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import CentredPlaceholderText from "./CentredPlaceholderText.svelte";

  const api = getContext<Api>(API_KEY);

  let { activeView, modifyAddons, addonListNav } = $props<{
    activeView: View;
    modifyAddons: (
      method: "install" | "update" | "remove" | "pin",
      addons: Addon[],
      extraParams?: { [key: string]: unknown },
    ) => Promise<void>;
    addonListNav: Snippet<[Partial<ComponentProps<AddonListNav>>]>;
  }>();

  let isInstalling = $state(false);

  let installedAddons = $state([] as Addon[]);
  let selections = $state([] as Addon[]);

  let addonListNavProps = $derived.by(() => ({
    reconcileInstallationInProgress: isInstalling,
    canReconcile: selections.length > 0,
    onInstallReconciledInstalled: installReconciledInstalled,
  }));

  const prepareReconcileInstalled = async () => {
    const results = await api.getReconcileInstalledCandidates();
    installedAddons = results.map((c) => c.installed_addon);
    return results;
  };

  const installReconciledInstalled = async () => {
    isInstalling = true;

    try {
      const addonsToRereconcile = selections
        .map((a, i) => [a, installedAddons[i]] as const)
        .filter(([a, b]) => a && !isSameAddon(a, b));

      await modifyAddons(
        "remove",
        addonsToRereconcile.map(([, a]) => a),
      );
      await modifyAddons(
        "install",
        addonsToRereconcile.map(([a]) => a),
        { replace: false },
      );

      activeView = View.Installed;
    } finally {
      isInstalling = false;
    }
  };
</script>

{@render addonListNav(addonListNavProps)}

{#await prepareReconcileInstalled()}
  <CentredPlaceholderText>Loading…</CentredPlaceholderText>
{:then result}
  {#if result.length}
    <AddonList>
      {#each result as { installed_addon, alternative_addons }, idx}
        <li>
          <AddonStub
            bind:selections
            folders={[{ name: installed_addon.name, version: "" }]}
            choices={[installed_addon, ...alternative_addons]}
            {idx}
            expanded={true}
          />
        </li>
      {/each}
    </AddonList>
  {:else}
    <CentredPlaceholderText>No alternative sources found</CentredPlaceholderText>
  {/if}
{/await}
