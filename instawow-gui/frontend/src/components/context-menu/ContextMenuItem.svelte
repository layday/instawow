<script lang="ts">
  import { getContext, type Snippet } from "svelte";
  import type { ContextMenuHandle } from "./ContextMenu.svelte";

  const contextMenu = getContext<ContextMenuHandle>("contextMenu");

  const {
    children,
    divider = false,
    onSelect,
  } = $props<
    (
      | {
          children?: never;
          divider: true;
        }
      | {
          children: Snippet;
          divider?: never;
        }
    ) & {
      onSelect?: () => void;
    }
  >();

  const onSelectWrapped = (event: MouseEvent) => {
    event.stopPropagation();

    if (!divider) {
      onSelect?.();
      contextMenu.hide();
    }
  };
</script>

<li class="menu-item">
  {#if divider}
    <hr />
  {:else}
    <button onclick={onSelectWrapped}>
      {@render children?.()}
    </button>
  {/if}
</li>

<style lang="scss">
  @use "../scss/vars";

  .menu-item {
    button {
      margin: 0;
      padding: 0 0.8rem;
      border: 0;
      line-height: 1.38rem;
      width: 100%;
      text-align: left;

      &:focus,
      &:hover {
        background-color: vars.$action-button-bg-color;
        color: vars.$action-button-text-color;
      }
    }

    hr {
      margin: 0.4rem;
      border: 1px solid var(--inverse-color-alpha-20);
    }
  }
</style>
