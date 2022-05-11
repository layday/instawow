<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { Addon } from "../api";
  import { Strategy } from "../api";
  import { AddonAction } from "../constants";
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
      selection: AddonAction;
    };
  }>();
</script>

<ContextMenu bind:show {eventX} {eventY}>
  {#if installed}
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", {
          addon,
          selection: AddonAction.VisitHomepage,
        })}>Visit home page</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", {
          addon,
          selection: AddonAction.ViewChangelog,
        })}>View changelog</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", {
          addon,
          selection: AddonAction.RevealFolder,
        })}>Reveal folder</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: AddonAction.Resolve })}
      >Resolve</ContextMenuItem
    >
    <ContextMenuItem divider />
    {#if supportsRollback}
      {#if addon.logged_versions.length > 1}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", {
              addon,
              selection: AddonAction.Rollback,
            })}>Rollback</ContextMenuItem
        >
      {/if}
      {#if addon.options.strategy === Strategy.version}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: AddonAction.Unpin })}
          >Unpin</ContextMenuItem
        >
      {:else}
        <ContextMenuItem
          on:click={() =>
            dispatch("requestHandleContextMenuSelection", { addon, selection: AddonAction.Pin })}
          >Pin</ContextMenuItem
        >
      {/if}
    {/if}
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", {
          addon,
          selection: AddonAction.Unreconcile,
        })}>Unreconcile</ContextMenuItem
    >
  {:else}
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", {
          addon,
          selection: AddonAction.InstallAndReplace,
        })}>Install and replace</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", {
          addon,
          selection: AddonAction.ViewChangelog,
        })}>View changelog</ContextMenuItem
    >
    <ContextMenuItem divider><hr /></ContextMenuItem>
    <ContextMenuItem
      on:click={() =>
        dispatch("requestHandleContextMenuSelection", { addon, selection: AddonAction.Resolve })}
      >Resolve</ContextMenuItem
    >
  {/if}
</ContextMenu>
