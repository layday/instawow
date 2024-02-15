<script lang="ts">
  import { DateTime } from "luxon";
  import { getContext } from "svelte";
  import type { Addon } from "../api";
  import type { ModalHandle } from "./modal/Modal.svelte";

  let { addon, onRequestRollback } = $props<{
    addon: Addon;
    onRequestRollback: (addon: Addon) => void;
  }>();

  const { hide } = getContext<ModalHandle>("modal");

  let selectedVersion = $state("");

  const onRequestRollbackAndHide = (event: Event) => {
    event.preventDefault();

    onRequestRollback({
      ...addon,
      version: selectedVersion,
      options: {
        ...addon.options,
        version_eq: true,
      },
    });
    hide();
  };
</script>

<div class="title-bar">rollback</div>
<form class="content" onsubmit={onRequestRollbackAndHide}>
  <select class="row form-control" aria-label="strategy" bind:value={selectedVersion}>
    {#each addon.logged_versions as version}
      <option value={version.version} disabled={addon.version === version.version}>
        {version.version}
        (installed
        {DateTime.fromISO(version.install_time).toRelative()})
      </option>
    {/each}
  </select>
  <button class="row form-control" type="submit">rollback</button>
</form>
