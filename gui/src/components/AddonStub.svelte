<script lang="ts">
  import type { Addon, AddonMatch } from "../api";
  import { faChevronCircleDown, faChevronCircleUp } from "@fortawesome/free-solid-svg-icons";
  import { ipcRenderer } from "electron";
  import Icon from "./SvgIcon.svelte";

  export let selections: Addon[], folders: AddonMatch["folders"], choices: Addon[], idx: number;

  let selectionIdx = 0;
  let selection: Addon;

  $: selection = selections[idx] = choices[selectionIdx];
</script>

<style lang="scss">
  @import "vars";

  .addon-stub {
    position: relative;
    display: flex;
    padding: 0.4em 0.75em;
    transition: all 0.2s;

    > div {
      flex-grow: 1;
      overflow-x: hidden;
      white-space: nowrap;

      .folders {
        overflow-x: hidden;
        text-overflow: ellipsis;
      }

      .main-folder {
        font-weight: 500;
      }

      .remaining-folders {
        font-size: 0.8em;
      }
    }
  }

  .selection-controls {
    margin: 0.35rem 0 0.2rem;
    padding: 0.1rem 0.2rem 0 0.5rem;
    background-color: var(--inverse-color-10);
    border-radius: 4px;

    summary {
      display: grid;
      grid-template-columns: 1fr 2fr 1.5rem;
      grid-column-gap: 0.5rem;
      line-height: 2.2;

      &::-webkit-details-marker {
        display: none;
      }

      :last-child {
        justify-self: right;
      }

      :global(.icon) {
        display: block;
        margin-top: 3px;
        height: 16px;
        width: 16px;
        fill: var(--inverse-color);
      }
    }

    .defn-and-version {
      font-family: Menlo, monospace;
      font-size: 0.7rem;
    }

    &[open] :global(.icon-collapsed) {
      display: none;
    }

    &:not([open]) :global(.icon-expanded) {
      display: none;
    }
  }

  .choices {
    @include unstyle-list;
    margin-left: -0.5rem;
    padding-bottom: 0.3rem;

    li {
      display: flex;
      align-items: center;
      margin-left: 0.5rem;

      label {
        flex-grow: 1;
        line-height: 1em;
        padding-left: 0.25em;
        border-radius: 1em;

        a {
          font-size: 0.8em;
          color: var(--inverse-color-tone-20);
        }
      }
    }

    [type="radio"] {
      -webkit-appearance: none;
      flex-shrink: 0;
      width: 12px;
      height: 12px;
      margin: 0;
      border-radius: 1rem;
      border: 1px solid var(--inverse-color);

      &:checked {
        background-color: var(--inverse-color);
      }
    }
  }
</style>

<div class="addon-stub">
  <div>
    <div class="folders">
      <span class="main-folder">{folders[0].name}</span>
      {#if folders.length > 1}
        <span class="remaining-folders">
          {folders
            .slice(1)
            .map((f) => f.name)
            .join(', ')}
        </span>
      {/if}
    </div>
    {#if choices.length}
      <!-- open={false} is needed for the [open] CSS selector to be compiled -->
      <details class="selection-controls" open={false}>
        <summary>
          <div aria-label="installed version" class="defn-and-version">
            {folders.find((f) => f.version)?.version || '?'}
          </div>
          <!-- prettier-ignore -->
          <div aria-label="selection" class="defn-and-version">
            ({choices.length})
            {#if selection}
              {selection.source}:{selection.slug}==<span title={selection.date_published}>{selection.version}</span>
            {:else}
              skip
            {/if}
          </div>
          <div>
            <Icon class="icon icon-collapsed" icon={faChevronCircleDown} />
            <Icon class="icon icon-expanded" icon={faChevronCircleUp} />
          </div>
        </summary>
        <ul class="choices">
          {#each choices as choice, choiceIdx}
            <li>
              <input
                type="radio"
                name="addon-selection-{idx}"
                id="addon-selection-{idx}-{choiceIdx}"
                value={choiceIdx}
                bind:group={selectionIdx} />
              <label for="addon-selection-{idx}-{choiceIdx}">
                <span class="defn-and-version">
                  {choice.source}:{choice.slug}=={choice.version}
                </span>
                <a
                  class="open-url"
                  href="__openUrl"
                  on:click|preventDefault|stopPropagation={() => ipcRenderer.send('open-url', choice.url)}>
                  (open in browser)
                </a>
              </label>
            </li>
          {/each}
          <li>
            <input
              type="radio"
              name="addon-selection-{idx}"
              id="addon-selection-{idx}-skip"
              value={-1}
              bind:group={selectionIdx} />
            <label for="addon-selection-{idx}-skip">
              <span class="defn-and-version">skip</span>
            </label>
          </li>
        </ul>
      </details>
    {/if}
  </div>
</div>
