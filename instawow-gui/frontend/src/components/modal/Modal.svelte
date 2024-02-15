<script lang="ts" context="module">
  export interface ModalHandle {
    hide(): void;
  }
</script>

<script lang="ts">
  import { setContext, type Snippet } from "svelte";
  import { fade, scale } from "svelte/transition";

  const { children, onHide } = $props<{
    children: Snippet;
    onHide?: () => void;
  }>();

  const hideOnEsc = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onHide?.();
    }
  };

  setContext<ModalHandle>("modal", {
    hide: () => onHide?.(),
  });
</script>

<svelte:window onkeydown={hideOnEsc} />

<div
  class="modal-overlay"
  role="presentation"
  onclick={onHide}
  transition:fade={{ duration: 200 }}
>
  <div class="modal-wrapper" role="presentation" onclick={(e) => e.stopPropagation()}>
    <dialog class="modal" open aria-modal="true" in:scale={{ duration: 200 }}>
      {@render children()}
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
