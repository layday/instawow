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

<li class="menu-item">
  {#if divider}
    <hr />
  {:else}
    <button on:click|stopPropagation={handleClick}><slot /></button>
  {/if}
</li>

<style lang="scss">
  @use "scss/vars";

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
