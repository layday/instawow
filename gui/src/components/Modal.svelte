<script lang="ts">
  import { fade } from "svelte/transition";

  export let show: boolean;

  const dismissOnEsc = () => {
    const handler = (e) => e.key === "Escape" && (show = false);
    document.body.addEventListener("keydown", handler);

    return {
      destroy: () => document.body.removeEventListener("keydown", handler),
    };
  };
</script>

<style lang="scss">
  .modal-wrapper {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 0;
    right: 0;
    background-color: var(--base-color-65);
    z-index: 10;
  }
</style>

<div class="modal-wrapper" transition:fade={{ duration: 200 }} use:dismissOnEsc>
  <slot />
</div>
