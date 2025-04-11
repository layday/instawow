<script lang="ts">
  import { DateTime } from "luxon";
  import { getContext } from "svelte";
  import type { Addon, AddonVersion } from "../api";
  import type { ModalHandle } from "./modal/Modal.svelte";

  let {
    addon,
    loggedVersions,
    onRequestRollback,
  }: {
    addon: Addon;
    loggedVersions: AddonVersion[];
    onRequestRollback: (addon: Addon) => void;
  } = $props();

  const { hide } = getContext<ModalHandle>("modal");

  let selectedVersion = $state(
    loggedVersions.find(({ version }) => version != addon.version)?.version ?? "",
  );

  const onRequestRollbackAndHide = (event: Event) => {
    event.preventDefault();

    onRequestRollback({
      ...addon,
      version: selectedVersion,
      options: { ...addon.options, version_eq: true },
    });
    hide();
  };
</script>

<div class="title-bar">rollback</div>
<form class="content" onsubmit={onRequestRollbackAndHide}>
  {#if loggedVersions.length > 1}
    <select class="row form-control" aria-label="strategy" bind:value={selectedVersion}>
      {#each loggedVersions as version}
        <option value={version.version} disabled={addon.version === version.version}>
          {version.version}
          (installed
          {DateTime.fromISO(version.install_time).toRelative()})
        </option>
      {/each}
    </select>
    <button class="row form-control" type="submit">rollback</button>
  {:else}
    <p>No older versions found.</p>
  {/if}
</form>
