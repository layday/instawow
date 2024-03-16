<script lang="ts">
  import { getContext, type Snippet } from "svelte";
  import { isSameAddon } from "../addon";
  import { type Addon } from "../api";
  import { API_KEY, type Api } from "../stores/api.svelte";
  import AddonList from "./AddonList.svelte";
  import AddonStub from "./AddonStub.svelte";
  import CentredPlaceholderText from "./CentredPlaceholderText.svelte";
  import Spinner from "./Spinner.svelte";

  const api = getContext<Api>(API_KEY);

  let {
    profileNav,
    onRereconcile,
  }: {
    profileNav: Snippet<[navMiddle: Snippet | undefined, navEnd: Snippet | undefined]>;
    onRereconcile: (addonPairs: typeof addonsToRereconcile) => Promise<void>;
  } = $props();

  let isRereconciling = $state(false);

  let installedAddons = $state([] as Addon[]);
  let selections = $state([] as Addon[]);

  let addonsToRereconcile = $derived(
    selections
      .map((a, i) => [a, installedAddons[i]] as const)
      .filter(([a, b]) => a && !isSameAddon(a, b)),
  );

  const prepareReconcileInstalled = async () => {
    const results = await api.getReconcileInstalledCandidates();
    installedAddons = results.map((c) => c.installed_addon);
    return results;
  };

  const onRereconcileWrapped = async () => {
    isRereconciling = true;
    try {
      await onRereconcile(addonsToRereconcile);
    } finally {
      isRereconciling = false;
    }
  };
</script>

{#snippet navEnd()}
  {#if isRereconciling}
    <Spinner />
  {/if}

  <menu class="control-set">
    <li>
      <button
        class="control"
        disabled={isRereconciling || !addonsToRereconcile.length}
        onclick={onRereconcileWrapped}
      >
        switch sources
      </button>
    </li>
  </menu>
{/snippet}

{@render profileNav(undefined, navEnd)}

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
