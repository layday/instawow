<script lang="ts">
  import { createEventDispatcher, getContext } from "svelte";
  import type { ContextMenuHandle } from "./ContextMenu.svelte";

  export let divider = false;

  const contextMenu = getContext<ContextMenuHandle>("contextMenu");

  const dispatch = createEventDispatcher<{
    click: void;
  }>();

  const handleClick = () => {
    if (!divider) {
      contextMenu.hide();
      dispatch("click");
    }
  };
</script>

<li class:divider on:click|stopPropagation={handleClick}>
  {#if divider}
    <hr />
  {:else}
    <slot />
  {/if}
</li>

<style lang="scss">
  @use "scss/vars";

  li {
    padding: 0 0.8rem;
    line-height: 1.2rem;

    &:not(.divider):hover {
      background-color: vars.$action-button-bg-color;
      color: vars.$action-button-text-color;
    }

    hr {
      border: 1px solid var(--inverse-color-alpha-20);
    }
  }
</style>
