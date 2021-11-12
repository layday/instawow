<script lang="ts">
  import type { Addon, AddonWithMeta } from "../api";
  import { Strategy } from "../api";
  import { api } from "../store";
  import {
    faEllipsisH,
    faExternalLinkSquareAlt,
    faTrashAlt,
  } from "@fortawesome/free-solid-svg-icons";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";
  import ProgressIndicator from "./ProgressIndicator.svelte";
  import Icon from "./SvgIcon.svelte";

  export let addon: AddonWithMeta,
    otherAddon: Addon,
    beingModified: boolean,
    showCondensed: boolean,
    installedIsRefreshing: boolean,
    downloadProgress: number;

  const dispatch = createEventDispatcher();

  $: isOutdated = addon.version !== otherAddon.version;
</script>

<div
  class="addon"
  class:status-outdated={isOutdated}
  class:status-pinned={addon.options.strategy === Strategy.version}
  class:status-being-modified={beingModified}
>
  <ul class="addon-details" class:two-col={showCondensed}>
    <li class="name">{addon.name}</li>
    <li class="versions">
      {addon.version}
      {#if isOutdated}{"< "}{otherAddon.version}{/if}
      <span class="date" title={otherAddon.date_published}>
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
    <div class="progress-indicator" in:fade>
      <ProgressIndicator diameter={18} progress={downloadProgress} />
    </div>
  {:else}
    <menu class="addon-actions">
      {#if addon.__installed__}
        {#if isOutdated}
          <li>
            <button
              disabled={installedIsRefreshing}
              on:click|stopPropagation={() => dispatch("requestUpdate")}>update</button
            >
          </li>
          <li>
            <button on:click|stopPropagation={() => dispatch("requestShowChangelogModal")}
              >changelog</button
            >
          </li>
        {/if}
        <li>
          <button
            aria-label="remove"
            title="remove"
            disabled={installedIsRefreshing}
            on:click|stopPropagation={() => dispatch("requestRemove")}
          >
            <Icon icon={faTrashAlt} />
          </button>
        </li>
        <li>
          <button
            aria-label="show options"
            title="show options"
            on:click|stopPropagation={(e) => dispatch("requestShowAddonInstalledContextMenu", e)}
          >
            <Icon icon={faEllipsisH} />
          </button>
        </li>
      {:else}
        <li>
          <button on:click|stopPropagation={() => dispatch("requestInstall")}>install</button>
        </li>
        <li>
          <button
            aria-label="open in browser"
            title="open in browser"
            on:click|stopPropagation={() => $api.openUrl(addon.url)}
          >
            <Icon icon={faExternalLinkSquareAlt} />
          </button>
        </li>
        <li>
          <button
            aria-label="show options"
            title="show options"
            on:click|stopPropagation={(e) =>
              dispatch("requestShowAddonNotInstalledContextMenu", e)}
          >
            <Icon icon={faEllipsisH} />
          </button>
        </li>
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

    &.status-outdated {
      @include striped-background(-45deg, rgba(lime, 0.1));
    }

    &.status-pinned {
      @include striped-background(-45deg, rgba(gold, 0.1));
    }
  }

  .addon-details {
    @extend %unstyle-list;
    flex-grow: 1;
    align-items: baseline;
    gap: 0.5em;
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

    .name {
      font-weight: 700;
      white-space: nowrap;
      text-overflow: ellipsis;
      overflow-x: hidden;
    }

    .versions {
      float: right;
      text-align: right;
    }

    .date {
      white-space: nowrap;
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
    $middle-border-radius: 0.75em;
    $edge-border-radius: 1em;

    @extend %unstyle-list;
    display: flex;
    flex-wrap: nowrap;
    align-self: center;
    padding-left: 0.5rem;

    li {
      + li {
        margin-left: 4px;
      }

      &:first-child button {
        border-top-left-radius: $edge-border-radius;
        border-bottom-left-radius: $edge-border-radius;
      }

      &:last-child button {
        border-top-right-radius: $edge-border-radius;
        border-bottom-right-radius: $edge-border-radius;
      }
    }

    button {
      margin: 0;
      padding: 0 0.625rem;
      height: 1.8em;
      line-height: 1.8em;
      font-size: 0.8em;
      font-weight: 600;
      border: 0;
      border-radius: $middle-border-radius;
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: $action-button-focus-bg-color;
      }

      :global(.icon) {
        display: block;
        width: 0.8rem;
        height: 0.8rem;
        fill: $action-button-text-color;
      }
    }
  }

  .progress-indicator {
    align-self: center;
    justify-self: right;
    margin-left: 0.75em;

    :global(circle) {
      stroke: $action-button-bg-color;
    }
  }
</style>
