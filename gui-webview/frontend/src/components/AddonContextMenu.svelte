<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import type { Addon } from "../api";
  import { AddonAction } from "../constants";
  import ContextMenu, { type EventCoords } from "./ContextMenu.svelte";
  import ContextMenuItem from "./ContextMenuItem.svelte";

  interface Details {
    addon: Addon;
    installed: boolean;
    supportsRollback: boolean;
  }

  let contextMenu: ContextMenu;

  let details: Details;

  export const show = (eventCoords: EventCoords, theseDetails: Details) => {
    details = theseDetails;
    contextMenu.show(eventCoords);
  };

  const dispatch = createEventDispatcher<{
    selectItem: {
      addon: Addon;
      selection: AddonAction;
    };
  }>();
</script>

<ContextMenu bind:this={contextMenu}>
  {#if details?.installed}
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.VisitHomepage,
        })}>Visit home page</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.ViewChangelog,
        })}>View changelog</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.RevealFolder,
        })}>Reveal folder</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.Resolve,
        })}>Resolve</ContextMenuItem
    >
    <ContextMenuItem divider />
    {#if details?.supportsRollback}
      {#if details.addon.logged_versions.length > 1}
        <ContextMenuItem
          on:click={() =>
            dispatch("selectItem", {
              addon: details.addon,
              selection: AddonAction.Rollback,
            })}>Rollback</ContextMenuItem
        >
      {/if}
      {#if details.addon.options.version_eq}
        <ContextMenuItem
          on:click={() =>
            dispatch("selectItem", {
              addon: details.addon,
              selection: AddonAction.Unpin,
            })}>Unpin</ContextMenuItem
        >
      {:else}
        <ContextMenuItem
          on:click={() =>
            dispatch("selectItem", {
              addon: details.addon,
              selection: AddonAction.Pin,
            })}>Pin</ContextMenuItem
        >
      {/if}
    {/if}
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.Unreconcile,
        })}>Unreconcile</ContextMenuItem
    >
  {:else}
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.InstallAndReplace,
        })}>Install and replace</ContextMenuItem
    >
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.ViewChangelog,
        })}>View changelog</ContextMenuItem
    >
    <ContextMenuItem divider><hr /></ContextMenuItem>
    <ContextMenuItem
      on:click={() =>
        dispatch("selectItem", {
          addon: details.addon,
          selection: AddonAction.Resolve,
        })}>Resolve</ContextMenuItem
    >
  {/if}
</ContextMenu>
