<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { Addon } from "../api";
  import { Strategy } from "../api";
  import ContextMenu from "./ContextMenu.svelte";
  import ContextMenuItem from "./ContextMenuItem.svelte";

  export let show: boolean,
    eventX: number,
    eventY: number,
    addon: Addon,
    installed: boolean,
    supportsRollback: boolean;

  const dispatch = createEventDispatcher<{
    requestHandleContextMenuSelection: {
      addon: Addon;
      selection: string;
    };
  }>();
</script>

<ContextMenu bind:show {eventX} {eventY}>
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
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: "resolve" })}
      >Resolve</ContextMenuItem
    >
    <ContextMenuItem divider />
    {#if supportsRollback}
      {#if addon.logged_versions.length > 1}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: "rollback" })}
          >Rollback</ContextMenuItem
        >
      {/if}
      {#if addon.options.strategy === Strategy.version}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: "unpin" })}
          >Unpin</ContextMenuItem
        >
      {:else}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: "pin" })}
          >Pin</ContextMenuItem
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
