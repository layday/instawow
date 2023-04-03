<script lang="ts" context="module">
  export interface ModalHandle {
    dismiss(): void;
  }
</script>

<script lang="ts">
  import { createEventDispatcher, setContext } from "svelte";
  import { fade, scale } from "svelte/transition";

  const dispatch = createEventDispatcher<{
    dismiss: void;
  }>();

  export const dismiss = () => {
    dispatch("dismiss");
  };

  const dismissOnEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      dismiss();
      event.preventDefault();
    }
  };

  setContext("modal", {
    dismiss,
  });
</script>

<svelte:window on:keydown={dismissOnEsc} />

<div class="modal-wrapper" transition:fade={{ duration: 200 }} on:click={dismiss}>
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
  @use "../scss/vars";

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
