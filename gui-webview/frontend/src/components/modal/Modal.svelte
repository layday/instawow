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

<div
  class="modal-overlay"
  role="presentation"
  transition:fade={{ duration: 200 }}
  on:click={dismiss}
>
  <div class="modal-wrapper" role="presentation" on:click|stopPropagation>
    <dialog class="modal" open aria-modal="true" in:scale={{ duration: 200 }}>
      <slot />
    </dialog>
  </div>
</div>

<style lang="scss">
  @use "../scss/vars";

  .modal-overlay {
    @extend %cover-canvas;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .modal-wrapper {
    display: contents;
  }

  .modal {
    display: flex;
    flex-direction: column;
    max-height: 75%;
  }
</style>
