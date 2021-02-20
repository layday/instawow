<script lang="ts">
  import type { Addon } from "../api";
  import { Strategy } from "../api";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, addon: Addon, addonListEl: HTMLElement;

  const dispatch = createEventDispatcher();

  let version: string;

  const requestRollback = () => {
    dispatch("requestRollback", {
      ...addon,
      version: version,
      options: { strategy: Strategy.version },
    });
    show = false;
  };
</script>

<Modal bind:show {addonListEl}>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
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
  </dialog>
</Modal>

<style lang="scss">
  @import "scss/modal";
</style>
