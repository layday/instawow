<script lang="ts">
  import type { Defn, Sources } from "../api";
  import { createEventDispatcher } from "svelte";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, source: Sources["foo"], defn: Defn;

  const strategyExplanations = {
    default: "latest stable version",
    latest: "latest version of any quality",
    curse_latest_beta: "latest beta from CurseForge",
    curse_latest_alpha: "latest alpha from CurseForge",
    any_flavour: "latest stable version for any game flavour",
    version: "specific version to install",
  };

  const dispatch = createEventDispatcher();
  const label = show;

  let strategy: string;
  let strategyVals: string[] = [];

  const requestInstallOrReinstall = () => {
    dispatch(show === "install" ? "requestInstall" : "requestReinstall", {
      ...defn,
      strategy: strategy,
      strategy_vals: strategyVals,
    });
    show = false;
  };
</script>

<style lang="scss">
  @import "modal";
</style>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">{label} with strategy</div>
    <form class="content" on:submit|preventDefault={() => requestInstallOrReinstall()}>
      <select class="row" aria-label="strategy" bind:value={strategy}>
        {#each source.supported_strategies as strategy}
          <option value={strategy}>{strategy} ({strategyExplanations[strategy]})</option>
        {/each}
      </select>
      <!-- <div class="row explanation">{strategyExplanations[strategy]}</div> -->
      {#if strategy === 'version'}
        <input
          aria-label="version"
          class="row"
          type="text"
          placeholder="version"
          required
          on:change={(e) => (strategyVals = [e.target.value])} />
      {/if}
      <button class="row" type="submit">{label}</button>
    </form>
  </dialog>
</Modal>
