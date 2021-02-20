<script lang="ts">
  import type { Addon, AddonWithMeta } from "../api";
  import { Strategy } from "../api";
  import { ipcRenderer } from "../ipc";
  import {
    faEllipsisH,
    faExternalLinkSquareAlt,
    faHistory,
  } from "@fortawesome/free-solid-svg-icons";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";
  import Icon from "./SvgIcon.svelte";

  export let addon: AddonWithMeta,
    otherAddon: Addon,
    isOutdated: boolean,
    supportsRollback: boolean,
    beingModified: boolean,
    showCondensed: boolean,
    installed__isRefreshing: boolean;

  const dispatch = createEventDispatcher();
</script>

<div
  class="addon"
  class:status-damaged={false}
  class:status-outdated={isOutdated}
  class:status-pinned={addon.options.strategy === Strategy.version}
  class:status-being-modified={beingModified}
>
  <ul class="addon-details" class:two-col={showCondensed}>
    <li class="name">{addon.name}</li>
    <li class="versions">
      {addon.version}
      {#if isOutdated}{"<"} {otherAddon.version}{/if}
      <span title={otherAddon.date_published}>
        ({DateTime.fromISO(otherAddon.date_published).toRelative()})
      </span>
      {#if otherAddon.options.strategy !== Strategy.default}@ {otherAddon.options.strategy}{/if}
    </li>
    {#if !showCondensed}
      <li class="defn">{addon.source}:{addon.id}</li>
      <li class="description">{addon.description || "No description."}</li>
    {/if}
  </ul>
  {#if beingModified}
    <div class="modification-status-indicator" in:fade />
  {:else}
    <menu class="addon-actions">
      {#if addon.__installed__}
        {#if isOutdated}
          <button
            disabled={installed__isRefreshing}
            on:click|stopPropagation={() => dispatch("requestUpdate")}>update</button
          >
        {/if}
        {#if supportsRollback && addon.logged_versions.length > 1}
          <button
            aria-label="rollback"
            title="rollback"
            disabled={installed__isRefreshing}
            on:click|stopPropagation={() => dispatch("requestShowRollbackModal")}
          >
            <Icon icon={faHistory} />
          </button>
        {/if}
        <button
          disabled={installed__isRefreshing}
          on:click|stopPropagation={() => dispatch("requestRemove")}>remove</button
        >
        <button
          aria-label="show options"
          title="show options"
          on:click|stopPropagation={() => dispatch("showGenericAddonContextMenu")}
        >
          <Icon icon={faEllipsisH} />
        </button>
      {:else}
        <button
          aria-label="open in browser"
          title="open in browser"
          on:click|stopPropagation={() => ipcRenderer.send("open-url", addon.url)}
        >
          <Icon icon={faExternalLinkSquareAlt} />
        </button>
        <button on:click|stopPropagation={() => dispatch("requestInstall")}>install</button>
        <button
          aria-label="show options"
          title="show options"
          on:click|stopPropagation={() => dispatch("showInstallAddonContextMenu")}
        >
          <Icon icon={faEllipsisH} />
        </button>
      {/if}
    </menu>
  {/if}
</div>

<style lang="scss">
  @import "scss/vars";

  .addon {
    position: relative;
    display: flex;
    padding: 0.4em 0.75em;
    border-radius: inherit;
    transition: all 0.2s;

    &.status-being-modified {
      pointer-events: none;
    }

    &.status-damaged {
      @include striped-background(-45deg, rgba(red, 0.1));
    }

    &.status-outdated {
      @include striped-background(-45deg, rgba(lime, 0.1));
    }

    &.status-pinned {
      @include striped-background(-45deg, rgba(gold, 0.1));
    }
  }

  .addon-details {
    @include unstyle-list;
    flex-grow: 1;
    overflow-x: hidden;

    &.two-col {
      display: flex;
      line-height: 1.5rem;

      .name {
        flex-grow: 1;
      }

      .versions {
        margin-top: 0;
      }
    }

    li {
      display: block;
    }

    .name {
      font-weight: 600;
    }

    .versions {
      float: right;
    }

    .defn,
    .versions {
      margin-top: 0.25rem;
      font-family: $mono-font-stack;
      font-size: 0.7em;
      color: var(--inverse-color-tone-20);
    }

    .description {
      margin-top: 0.25rem;
      padding-left: 0.25rem;
      overflow-x: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      font-size: 0.8em;
    }

    &:hover .description {
      display: block;
    }
  }

  .addon-actions {
    @include unstyle-list;
    display: flex;
    flex-wrap: nowrap;
    align-self: center;
    padding-left: 0.625rem;

    button {
      padding: 0 0.625rem;
      line-height: 1.8em;
      font-size: 0.8em;
      font-weight: 600;
      border: 0;
      border-radius: 1em;
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: $action-button-focus-bg-color;
      }

      + button {
        margin-left: 4px;
      }

      :global(.icon) {
        display: block;
        width: 0.8rem;
        height: 0.8rem;
        fill: $action-button-text-color;
      }
    }
  }

  .modification-status-indicator {
    @include spinner(18px, $action-button-bg-color);
    align-self: center;
    justify-self: right;
    margin-left: 0.75em;
  }
</style>
