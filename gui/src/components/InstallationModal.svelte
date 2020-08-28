<script lang="ts">
  import type { Defn, Sources } from "../api";
  import { createEventDispatcher } from "svelte";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, source: Sources["foo"], defn: Defn;

  const dispatch = createEventDispatcher();

  let strategy: string;
  let strategyVals: string[] = [];

  const requestInstall = () => {
    dispatch("requestReinstall", { ...defn, strategy: strategy, strategy_vals: strategyVals });
    show = false;
  };
</script>

<style lang="scss">
  @import "modal";
</style>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <form on:submit|preventDefault={() => requestInstall()}>
      <select class="row" aria-label="strategy" bind:value={strategy}>
        {#each source.supported_strategies as strategy}
          <option value={strategy}>{strategy.replace(/_/g, ' ')}</option>
        {/each}
      </select>
      {#if strategy === 'version'}
        <input
          aria-label="version"
          class="row"
          type="text"
          placeholder="version"
          required
          on:change={(e) => (strategyVals = [e.target.value])} />
      {/if}
      <button class="row submit" type="submit">install</button>
    </form>
  </dialog>
</Modal>
