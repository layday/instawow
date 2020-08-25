<script lang="ts">
  import { faHistory, faEllipsisH } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import { DateTime } from "luxon";
  import { createEventDispatcher } from "svelte";
  import { fade } from "svelte/transition";
  import Icon from "./SvgIcon.svelte";

  export let addon, addonMeta, sources, refreshInProgress;

  let selected = false;
  let modifying = false;

  const modify = async (awaitable: Promise<any>) => {
    modifying = true;
    try {
      await awaitable;
    } finally {
      modifying = false;
    }
  };

  const dispatch = createEventDispatcher();

  const select = () => {
    selected = !selected;
    dispatch("requestSelect", { source: addon.source, name: addon.slug });
  };

  const requestInstall = () => {
    dispatch("requestInstall", { source: addon.source, name: addon.slug });
  };

  const requestReinstall = () => {
    dispatch("requestReinstall", { source: addon.source, name: addon.slug });
  };

  const requestUpdate = () => {
    dispatch("requestUpdate", { source: addon.source, name: addon.slug });
  };

  const requestRemove = () => {
    dispatch("requestRemove", { source: addon.source, name: addon.slug });
  };
</script>

<style lang="scss">
  @import "vars";

  $action-button-bg-color: rgb(24, 136, 255);
  $action-button-text-color: #efefef;

  .addon {
    position: relative;
    display: flex;
    padding: 0.4em 0.75em;
    transition: all 0.2s;

    &:nth-child(odd) {
      background-color: var(--inverse-color-05);
    }

    &.selected {
      $selected-color: rgb(2, 99, 225);
      background-color: $selected-color;
      color: #eee;

      .addon-details * {
        color: #ddd;
      }

      .addon-actions button {
        background-color: $action-button-text-color;
        color: $action-button-bg-color;

        :global(.icon) {
          fill: $action-button-bg-color;
        }
      }

      .modification-status-indicator {
        @include spinner(18px, $action-button-text-color);
      }
    }

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

    li {
      display: block;
    }

    .name {
      font-weight: 500;
    }

    .defn {
      a {
        color: var(--inverse-color-tone-20);
      }
    }

    .version {
      float: right;
    }

    .defn,
    .version {
      font-family: Menlo, monospace;
      font-size: 0.7em;
      line-height: 2em;
    }

    .description {
      font-size: 0.8em;
      overflow-x: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      color: var(--inverse-color-tone-10);
    }

    &:hover .description {
      display: block;
    }
  }

  .addon-actions {
    display: flex;
    flex-wrap: nowrap;
    align-self: center;
    justify-self: right;
    padding-left: 0.75em;
    -webkit-user-select: none;

    button {
      padding: 0 0.75em;
      line-height: 1.8em;
      font-size: 0.8em;
      font-weight: 500;
      border: 0;
      border-radius: 1em;
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:focus {
        background-color: rgb(0, 104, 217);
      }

      + button {
        margin-left: 0.5em;
      }

      :global(.icon) {
        display: block;
        width: 11px;
        height: 11px;
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

<li
  class="addon"
  class:selected
  class:status-damaged={addonMeta.damaged}
  class:status-outdated={addonMeta.new_version && addon.version !== addonMeta.new_version}
  class:status-pinned={addon.options.strategy === 'version'}
  class:status-being-modified={modifying}
  on:click={select}>
  <ul class="addon-details">
    <li class="name">{addon.name}</li>
    <!-- prettier-ignore -->
    <li class="version">
      {addon.version}
      (<span title={addon.date_published}><!--
        -->{DateTime.fromISO(addon.date_published).toRelative()}<!--
      --></span>)
      {#if addonMeta.new_version && addon.version !== addonMeta.new_version}
        {`< ${addonMeta.new_version}`}
      {/if}
      {#if addon.options.strategy !== 'default'}@ {addon.options.strategy}{/if}
    </li>
    <li class="defn">
      <a
        href="#__openUrl"
        on:click|preventDefault|stopPropagation={() => ipcRenderer.send('open-url', addon.url)}>
        {addon.source}:{addon.slug}
      </a>
    </li>
    <li class="description">{addon.description || 'No description.'}</li>
  </ul>
  {#if modifying}
    <div class="modification-status-indicator" transition:fade={{ duration: 200 }} />
  {:else}
    <nav class="addon-actions">
      {#if addonMeta.installed}
        {#if addonMeta.new_version && addon.version !== addonMeta.new_version}
          <button disabled={refreshInProgress} on:click|stopPropagation={() => (modifying = true)}>
            update
          </button>
        {/if}
        {#if addonMeta.damaged}
          <button disabled={refreshInProgress} on:click|stopPropagation>reinstall</button>
        {/if}
        {#if addon.logged_versions.length > 1 && sources[addon.source] && sources[addon.source].supports_rollback}
          <button
            label="rollback"
            title="rollback"
            disabled={refreshInProgress}
            on:click|stopPropagation
            on:contextmenu|preventDefault>
            <Icon icon={faHistory} />
          </button>
        {/if}
        <button label="more" title="more" disabled={refreshInProgress} on:click|stopPropagation>
          <Icon icon={faEllipsisH} />
        </button>
        <button disabled={refreshInProgress} on:click|stopPropagation={requestRemove}>
          remove
        </button>
      {:else}
        <button disabled={refreshInProgress} on:click|stopPropagation={requestInstall}>
          install
        </button>
      {/if}
    </nav>
  {/if}
</li>
