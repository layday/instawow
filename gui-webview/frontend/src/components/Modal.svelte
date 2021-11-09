<script lang="ts">
  import { fade } from "svelte/transition";

  export let show: boolean;

  const dismissOnEsc = (e: KeyboardEvent) => e.key === "Escape" && (show = false);
</script>

<svelte:window on:keydown={dismissOnEsc} />

<div class="modal-wrapper" transition:fade={{ duration: 200 }} on:click={() => (show = false)}>
  <slot />
</div>

<style lang="scss">
  @import "scss/vars";

  .modal-wrapper {
    @extend %cover-canvas;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: var(--base-color-alpha-65);
  }
</style>
