<script lang="ts">
  import { fade, scale } from "svelte/transition";

  export let show: boolean;

  const dismissOnEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape" && show) {
      show = false;
      event.preventDefault();
    }
  };
</script>

<svelte:window on:keydown={dismissOnEsc} />

<div class="modal-wrapper" transition:fade={{ duration: 200 }} on:click={() => (show = false)}>
  <dialog
    open
    class="modal"
    aria-modal="true"
    in:scale={{ duration: 200 }}
    on:click|stopPropagation
  >
    <slot />
  </dialog>
</div>

<style lang="scss">
  @use "scss/vars";

  .modal-wrapper {
    @extend %cover-canvas;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .modal {
    display: flex;
    flex-direction: column;
    max-height: 75%;
  }
</style>
