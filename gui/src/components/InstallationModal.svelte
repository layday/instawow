<script context="module" lang="ts">
  const strategyExplanations = {
    default: "latest stable version",
    latest: "latest version of any quality",
    curse_latest_beta: "latest beta from CurseForge",
    curse_latest_alpha: "latest alpha from CurseForge",
    any_flavour: "latest stable version for any game flavour",
    version: "specific version to install",
  };
</script>

<script lang="ts">
  import type { Defn, Sources } from "../api";
  import { createEventDispatcher } from "svelte";
  import { scale } from "svelte/transition";
  import Modal from "./Modal.svelte";

  export let show: any, source: Sources["foo"], defn: Defn;

  const dispatch = createEventDispatcher();
  const label = show;

  let strategy: string;
  let strategyVals: string[] = [];
  let replace: boolean = false;
  let newDefn: Defn;

  const requestInstallOrReinstall = () => {
    dispatch(show === "install" ? "requestInstall" : "requestReinstall", [newDefn, replace]);
    show = false;
  };

  // prettier-ignore
  $: newDefn = ({ ...defn, strategy: strategy, strategy_vals: strategyVals } as Defn);
</script>

<style lang="scss">
  @import "modal";
</style>

<Modal bind:show>
  <dialog open class="modal" in:scale={{ duration: 200 }} on:click|stopPropagation>
    <div class="title-bar">{label} with options</div>
    <form class="content" on:submit|preventDefault={() => requestInstallOrReinstall()}>
      {#if show === 'install'}
        <div class="row checkbox-array">
          <input id="__replace" type="checkbox" bind:checked={replace} />
          <label for="__replace">replace unreconciled add-on</label>
        </div>
      {/if}
      {#if source.supported_strategies.length > 1}
        <select class="row" aria-label="strategy" bind:value={strategy}>
          {#each source.supported_strategies as strategy}
            <option value={strategy}>{strategy} ({strategyExplanations[strategy]})</option>
          {/each}
        </select>
      {/if}
      {#if strategy === 'version'}
        <input
          aria-label="version"
          class="row"
          type="text"
          placeholder="version"
          required
          bind:value={strategyVals[0]} />
      {/if}
      <button class="row" type="submit">{label}</button>
    </form>
  </dialog>
</Modal>
