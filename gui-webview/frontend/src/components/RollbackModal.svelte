<script lang="ts">
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import type { Addon } from "../api";
  import { Strategy } from "../api";
  import Modal from "./Modal.svelte";

  export let show: boolean, addon: Addon;

  const dispatch = createEventDispatcher<{ requestRollback: Addon }>();

  let version: string;

  const requestRollback = () => {
    dispatch("requestRollback", {
      ...addon,
      version: version,
      options: { ...addon.options, strategy: Strategy.version },
    });
    show = false;
  };
</script>

<Modal bind:show>
  <div class="title-bar">rollback</div>
  <form class="content" on:submit|preventDefault={() => requestRollback()}>
    <select class="row" aria-label="strategy" bind:value={version}>
      {#each addon.logged_versions as version}
        <option value={version.version} disabled={addon.version === version.version}>
          {version.version}
          (installed
          {DateTime.fromISO(version.install_time).toRelative()})
        </option>
      {/each}
    </select>
    <button class="row" type="submit">rollback</button>
  </form>
</Modal>
