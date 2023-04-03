<script lang="ts">
  import { DateTime } from "luxon";
  import { createEventDispatcher, getContext } from "svelte";
  import type { Addon } from "../api";
  import type { ModalHandle } from "./modal/Modal.svelte";

  export let addon: Addon;

  const dispatch = createEventDispatcher<{ requestRollback: Addon }>();

  const { dismiss } = getContext<ModalHandle>("modal");

  let version: string;

  const requestRollbackAndHide = () => {
    dispatch("requestRollback", {
      ...addon,
      version,
      options: {
        ...addon.options,
        version_eq: true,
      },
    });
    dismiss();
  };
</script>

<div class="title-bar">rollback</div>
<form class="content" on:submit|preventDefault={() => requestRollbackAndHide()}>
  <select class="row form-control" aria-label="strategy" bind:value={version}>
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
