<script lang="ts">
  import { faQuestion } from "@fortawesome/free-solid-svg-icons";
  import { getContext, type Snippet } from "svelte";
  import { ReconciliationStage, type Addon } from "../api";
  import { API_KEY, type Api } from "../stores/api.svelte";
  import AddonList from "./AddonList.svelte";
  import AddonStub from "./AddonStub.svelte";
  import CentredPlaceholderText from "./CentredPlaceholderText.svelte";
  import SvgIcon from "./SvgIcon.svelte";
  import Spinner from "./Spinner.svelte";

  const api = getContext<Api>(API_KEY);

  const reconciliationStages = Object.values(ReconciliationStage);

  let {
    profileNav,
    onReconcile,
  }: {
    profileNav: Snippet<[navMiddle: Snippet | undefined, navEnd: Snippet | undefined]>;
    onReconcile: (
      stage: ReconciliationStage,
      stages: ReconciliationStage[],
      selections: Addon[],
      recursive?: boolean,
    ) => Promise<ReconciliationStage | undefined>;
  } = $props();

  let reconciliationStage = $state(reconciliationStages[0]);
  let selections = $state([] as Addon[]);

  let isReconciling = $state(false);

  const prepareReconcile = async () => {
    for (const [index, stage] of Array.from(reconciliationStages.entries()).slice(
      reconciliationStages.indexOf(reconciliationStage),
    )) {
      const results = await api.reconcile(stage);
      if (results.some((r) => r.matches.length) || !(index + 1 in reconciliationStages)) {
        reconciliationStage = stage;
        return results;
      }
    }
  };

  const onReconcileWrapped = async (recursive?: boolean) => {
    isReconciling = true;
    try {
      const nextStage = await onReconcile(
        reconciliationStage,
        reconciliationStages,
        selections,
        recursive,
      );
      reconciliationStage =
        nextStage ??
        reconciliationStages[reconciliationStages.indexOf(reconciliationStage) + 1] ??
        reconciliationStages[0];
    } finally {
      isReconciling = false;
    }
  };

  $effect.pre(() => {
    reconciliationStage; // Trigger

    selections = [];
  });
</script>

{#snippet navMiddle()}
  <menu class="control-set">
    <li>
      <select
        class="control reconciliation-stage-control"
        aria-label="reconciliation stage"
        disabled={isReconciling}
        bind:value={reconciliationStage}
      >
        {#each Object.values(ReconciliationStage) as stage}
          <option value={stage}>{stage}</option>
        {/each}
      </select>
    </li>
  </menu>
{/snippet}

{#snippet navEnd()}
  {#if isReconciling}
    <Spinner />
  {/if}

  <menu class="control-set">
    <li>
      <button
        class="control"
        disabled={isReconciling || !selections.length}
        onclick={() => onReconcileWrapped()}
      >
        install
      </button>
    </li>
    <li>
      <button class="control" disabled={isReconciling} onclick={() => onReconcileWrapped(true)}>
        automate
      </button>
    </li>
  </menu>
{/snippet}

{@render profileNav(navMiddle, navEnd)}

{#await prepareReconcile()}
  <CentredPlaceholderText>Loading…</CentredPlaceholderText>
{:then results}
  {#if results?.length}
    <div class="preamble">
      <SvgIcon icon={faQuestion} />
      <p>
        Reconciliation is the process by which installed add-ons are linked with add-ons from
        sources. This is done in three stages in decreasing order of accuracy. Add-ons do not
        always carry source metadata and <i>instawow</i>
        employs a number of heuristics to reconcile add-ons which cannot be positively identified. If
        you trust <i>instawow</i>
        to do this without supervision, press "<b>automate</b>". Otherwise, review your selections
        below and press "<b>install</b>" to proceed to the next stage. Reconciled add-ons will be
        reinstalled.
      </p>
    </div>

    <AddonList>
      {#each results as { folders, matches }, idx}
        <li>
          <AddonStub bind:selections {folders} choices={matches} {idx} />
        </li>
      {/each}
    </AddonList>
  {:else}
    <CentredPlaceholderText>Reconciliation complete</CentredPlaceholderText>
  {/if}
{/await}

<style lang="scss">
  .preamble {
    display: grid;
    grid-template-columns: 3rem 1fr;
    grid-column-gap: 0.8rem;
    align-items: center;
    margin-top: 0.4rem;
    padding: 0 1.6rem;
    font-size: 0.85em;
    background-image: linear-gradient(45deg, rgba(pink, 0.2), rgba(orange, 0.2));
    color: var(--inverse-color-tone-a);

    p {
      margin: 0.75rem 0;
    }

    :global(.icon) {
      width: 3rem;
      height: 3rem;
      fill: var(--inverse-color-tone-b);
    }
  }

  .reconciliation-stage-control {
    width: 100%;
    padding-right: 1.4rem;
    background-image: var(--dropdown-arrow);
    background-size: 10px;
    background-repeat: no-repeat;
    background-position: top calc(50% + 1px) right 7px;
  }
</style>
