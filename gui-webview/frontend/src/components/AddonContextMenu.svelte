<script lang="ts">
  import type { Addon } from "../api";
  import { createEventDispatcher } from "svelte";
  import { Strategy } from "../api";
  import ContextMenu from "./ContextMenu.svelte";
  import ContextMenuItem from "./ContextMenuItem.svelte";

  export let show: boolean,
    xOffset: number,
    yOffset: number,
    addon: Addon,
    installed: boolean,
    supportsRollback: boolean;

  const dispatch = createEventDispatcher();
</script>

<ContextMenu bind:show {xOffset} {yOffset}>
  {#if installed}
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "visit-home-page" })}
      >Visit home page</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "view-changelog" })}
      >View changelog</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "reveal-folder" })}
      >Reveal folder</ContextMenuItem
    >
    <ContextMenuItem divider><hr /></ContextMenuItem>
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "resolve" })}
      >Resolve</ContextMenuItem
    >
    {#if supportsRollback}
      {#if addon.options.strategy === Strategy.version}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: "pin" })}
          >Pin</ContextMenuItem
        >
      {:else}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: "unpin" })}
          >Unpin</ContextMenuItem
        >
      {/if}
    {/if}
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "unreconcile" })}
      >Unreconcile</ContextMenuItem
    >
  {:else}
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "install-and-replace" })}
      >Install and replace</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "view-changelog" })}
      >View changelog</ContextMenuItem
    >
    <ContextMenuItem divider><hr /></ContextMenuItem>
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "resolve" })}
      >Resolve</ContextMenuItem
    >
  {/if}
</ContextMenu>
