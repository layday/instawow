<script lang="ts">
  import type { Addon, AddonMatch } from "../api";
  import { api } from "../store";
  import { faChevronCircleDown, faChevronCircleUp } from "@fortawesome/free-solid-svg-icons";
  import Icon from "./SvgIcon.svelte";

  export let selections: Addon[], folders: AddonMatch["folders"], choices: Addon[], idx: number;

  let selectionIdx = 0;
  let selection: Addon;

  const getVersion = () => folders.find((f) => f.version)?.version || "?";

  $: selection = selections[idx] = choices[selectionIdx];
</script>

<div class="addon-stub">
  <div class="folders">
    <span class="main-folder">{folders[0].name}</span>
    {#if folders.length > 1}
      <span class="remaining-folders">
        {folders
          .slice(1)
          .map((f) => f.name)
          .join(", ")}
      </span>
    {/if}
  </div>
  {#if choices.length}
    <!-- open={false} is needed for the [open] CSS selector to be compiled -->
    <details class="selection-controls" open={false}>
      <summary>
        <div class="selection-grid">
          <div aria-label="installed version" class="defn-or-version">
            {getVersion()}
          </div>
          <!-- prettier-ignore -->
          <div aria-label="selection" class="defn-or-version">
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
        </div>
      </summary>
      <ul class="selection-grid choices">
        {#each choices as choice, choiceIdx}
          <li>
            <input
              type="radio"
              id="addon-selection-{idx}-{choiceIdx}"
              value={choiceIdx}
              bind:group={selectionIdx}
            />
            <label for="addon-selection-{idx}-{choiceIdx}">
              <span class="defn-or-version">{choice.source}:{choice.slug}=={choice.version}</span>
              <a
                class="open-url"
                title="open in browser"
                href="__openUrl"
                on:click|preventDefault|stopPropagation={() => $api.openUrl(choice.url)}
              >
                [↗]
              </a>
            </label>
          </li>
        {/each}
        <li>
          <input
            type="radio"
            id="addon-selection-{idx}-skip"
            value={-1}
            bind:group={selectionIdx}
          />
          <label for="addon-selection-{idx}-skip">
            <span class="defn-or-version">skip</span>
          </label>
        </li>
      </ul>
    </details>
  {/if}
</div>

<style lang="scss">
  @use "scss/vars";

  .addon-stub {
    transition: all 0.2s;
  }

  .folders,
  .selection-controls {
    padding: 0.4em 0.75em;
  }

  .folders {
    overflow-x: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-weight: 700;

    &:only-child {
      line-height: 1.5rem;
    }

    .remaining-folders {
      font-size: 0.8em;
      color: var(--inverse-color-tone-20);
    }
  }

  .defn-or-version {
    font-family: vars.$mono-font-stack;
    font-size: 0.7rem;
  }

  .selection-controls {
    margin-top: -0.25rem;
    padding-top: 0;
    color: var(--inverse-color-tone-20);

    .selection-grid {
      display: grid;
      grid-template-columns: 1fr 2fr 1rem;
      column-gap: 0.5rem;
    }

    summary {
      line-height: 1rem;

      &::-webkit-details-marker {
        display: none;
      }

      :nth-child(2) {
        padding: 0 0.2rem;
      }

      :last-child {
        justify-self: right;
      }

      :global(.icon) {
        display: block;
        height: 1rem;
        width: 1rem;
        fill: var(--inverse-color-tone-20);
      }
    }

    &[open] :global(.icon-collapsed) {
      display: none !important;
    }

    &:not([open]) :global(.icon-expanded) {
      display: none !important;
    }
  }

  .choices {
    @extend %unstyle-list;

    li {
      @extend .defn-or-version;
      display: flex;
      padding: 0 0.2rem;
      grid-column-start: 2;
      line-height: 1rem;

      &:first-child {
        margin-top: 0.18rem;
        padding-top: 0.18rem;
        border-top: 1px solid var(--inverse-color-tone-20);
      }

      label {
        flex-grow: 1;

        &::before {
          content: "( ) ";
        }
      }
    }

    [type="radio"] {
      display: none;

      &:checked + label::before {
        content: "(x) ";
      }
    }

    .open-url {
      color: var(--inverse-color-tone-20);
    }
  }
</style>
