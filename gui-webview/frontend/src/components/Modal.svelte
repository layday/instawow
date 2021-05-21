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
  .modal-wrapper {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    right: 0;
    z-index: 30;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: var(--base-color-alpha-65);
  }
</style>
