<script lang="ts">
  import type { Defn, Sources } from "../api";
  import { createEventDispatcher } from "svelte";

  export let show: boolean, source: Sources["foo"], defn: Defn;

  const dispatch = createEventDispatcher();

  let strategy: string;
  let strategyVals: string[] = [];

  const dismissOnEsc = () => {
    const handler = (e) => e.key === "Escape" && (show = false);
    document.body.addEventListener("keydown", handler);

    return {
      destroy: () => document.body.removeEventListener("keydown", handler),
    };
  };

  const requestInstall = () => {
    dispatch("requestReinstall", { ...defn, strategy: strategy, strategy_vals: strategyVals });
    show = false;
  };
</script>

<style lang="scss" global>
  @import "vars";

  .modal-wrapper {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    right: 0;
    background-color: var(--base-color-65);
    z-index: 10;
  }

  .modal {
    $form-el-line-height: 1.8em;
    $middle-border-radius: $form-el-line-height / 6;
    $edge-border-radius: $form-el-line-height / 4;

    position: fixed;
    top: 50%;
    bottom: 50%;
    z-index: 10;
    padding: 1.25rem;
    border: 0;
    border-radius: 0.25rem;
    box-shadow: 0 10px 20px var(--inverse-color-05);
    background-color: var(--base-color-65);
    backdrop-filter: blur(5px);
    color: var(--inverse-color);

    button,
    input,
    select {
      display: block;
      width: 100%;
      line-height: $form-el-line-height;
      padding: 0 0.75em;
      border: 0;
      border-radius: $edge-border-radius;
      background-color: var(--inverse-color-10);
      transition: background-color 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: var(--inverse-color-20);
      }

      &.error {
        background-color: salmon;
      }

      &.submit {
        background-color: $action-button-bg-color;
        color: $action-button-text-color;
        font-weight: 500;

        &:focus {
          background-color: $action-button-focus-bg-color;
        }
      }

      :global(.icon) {
        height: 16px;
        width: 16px;
        fill: var(--inverse-color);
        vertical-align: text-bottom;
      }
    }

    select {
      background-image: var(--dropdown-arrow);
      background-size: 10px;
      background-repeat: no-repeat;
      background-position: top 9px right 7px;
      min-width: 200px;
      -webkit-appearance: none;
    }

    .row + .row {
      margin-top: 0.5rem;
    }

    .select-folder-array {
      display: flex;

      button,
      input {
        border-radius: $middle-border-radius;

        + button,
        + input {
          margin-left: 4px;
        }
      }

      button {
        width: auto;
      }

      input {
        flex-grow: 1;
      }

      :first-child {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      :last-child {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }
    }

    .error-text {
      line-height: 1;
      color: salmon;
      font-size: 0.9em;

      :not(:first-child) {
        padding-top: 0.25rem;
      }
    }
  }
</style>

<div class="modal-wrapper">
  <dialog open={show} class="modal" use:dismissOnEsc>
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
          on:change={(e) => (strategyVals = [e.target.value])} />
      {/if}
      <button class="row submit" type="submit">install</button>
    </form>
  </dialog>
</div>
