<script lang="ts">
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import type { Addon } from "../api";
  import Modal from "./Modal.svelte";
  import lodash from "lodash";

  export let show: boolean, addon: Addon;

  const dispatch = createEventDispatcher<{ requestRollback: Addon }>();

  let version: string;

  const requestRollbackAndHide = () => {
    const newAddon = lodash.cloneDeep(addon);
    newAddon.version = version;
    newAddon.options.version_eq = true;
    dispatch("requestRollback", newAddon);
    show = false;
  };
</script>

<Modal bind:show>
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
</Modal>
