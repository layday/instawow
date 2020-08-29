<script lang="ts">
  import type { Addon, Defn } from "../api";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, defn: Defn, versions: Addon["logged_versions"];

  const dispatch = createEventDispatcher();

  let version: string;

  const requestReinstall = () => {
    dispatch("requestReinstall", { ...defn, strategy: "version", strategy_vals: [version] });
    show = false;
  };
</script>

<style lang="scss">
  @import "modal";
</style>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">rollback</div>
    <form class="content" on:submit|preventDefault={() => requestReinstall()}>
      <select class="row" aria-label="strategy" bind:value={version}>
        {#each versions as version}
          <option value={version.version}>
            {version.version} (installed {DateTime.fromISO(version.install_time).toRelative()})
          </option>
        {/each}
      </select>
      <button class="row" type="submit">install</button>
    </form>
  </dialog>
</Modal>
