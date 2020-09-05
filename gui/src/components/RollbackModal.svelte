<script lang="ts">
  import type { Addon, Defn } from "../api";
  import { Strategies } from "../api";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, defn: Defn, versions: Addon["logged_versions"], addonListEl: HTMLElement;

  const dispatch = createEventDispatcher();

  let version: string;

  const requestRollback = () => {
    dispatch("requestRollback", {
      ...defn,
      strategy: { type_: Strategies.version, version: version },
    });
    show = false;
  };
</script>

<style lang="scss">
  @import "modal";
</style>

<Modal bind:show {addonListEl}>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">rollback</div>
    <form class="content" on:submit|preventDefault={() => requestRollback()}>
      <select class="row" aria-label="strategy" bind:value={version}>
        {#each versions as version}
          <option value={version.version}>
            {version.version} (installed {DateTime.fromISO(version.install_time).toRelative()})
          </option>
        {/each}
      </select>
      <button class="row" type="submit">rollback</button>
    </form>
  </dialog>
</Modal>
