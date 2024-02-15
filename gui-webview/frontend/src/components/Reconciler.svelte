<script lang="ts">
  import { faQuestion } from "@fortawesome/free-solid-svg-icons";
  import { getContext, type ComponentProps, type Snippet } from "svelte";
  import { ReconciliationStage, type Addon } from "../api";
  import { API_KEY, type Api } from "../stores/api";
  import AddonList from "./AddonList.svelte";
  import AddonListNav from "./AddonListNav.svelte";
  import AddonStub from "./AddonStub.svelte";
  import CentredPlaceholderText from "./CentredPlaceholderText.svelte";
  import SvgIcon from "./SvgIcon.svelte";

  const reconciliationStages = Object.values(ReconciliationStage);
  const [initialReconciliationStage] = reconciliationStages;

  const api = getContext<Api>(API_KEY);

  let { modifyAddons, addonListNav } = $props<{
    modifyAddons: (
      method: "install" | "update" | "remove" | "pin",
      addons: Addon[],
      extraParams?: { [key: string]: unknown },
    ) => Promise<void>;
    addonListNav: Snippet<[Partial<ComponentProps<AddonListNav>>]>;
  }>();

  let isInstalling = $state(false);

  let reconciliationValues = $state({
    stage: initialReconciliationStage,
    selections: [] as Addon[],
  });

  let addonListNavProps = $derived.by(() => ({
    reconcileInstallationInProgress: isInstalling,
    "bind:reconcileStage": reconciliationValues.stage,
    canReconcile: reconciliationValues.selections.length > 0,
    onInstallReconciled: installReconciled,
    onAutomateReconciliation: () => installReconciled(reconciliationValues, true),
  }));

  const prepareReconcile = async () => {
    console.log(
      "what the",
      reconciliationValues.stage,
      [...reconciliationStages].slice(reconciliationStages.indexOf(reconciliationValues.stage)),
    );

    for (const [index, stage] of Array.from(reconciliationStages.entries()).slice(
      reconciliationStages.indexOf(reconciliationValues.stage),
    )) {
      const results = await api.reconcile(stage);
      if (results.some((r) => r.matches.length) || !(index + 1 in reconciliationStages)) {
        reconciliationValues = { stage, selections: [] }; // ???
        return results;
      }
    }
  };

  const installReconciled = async (
    { stage, selections }: typeof reconciliationValues = reconciliationValues,
    recursive?: boolean,
  ) => {
    isInstalling = true;

    try {
      await modifyAddons("install", selections.filter(Boolean), { replace: true });

      const nextStage = reconciliationStages[reconciliationStages.indexOf(stage) + 1];
      if (nextStage) {
        if (recursive) {
          const nextSelections = (await api.reconcile(stage))
            .filter((r) => r.matches.length)
            .map(({ matches: [addon] }) => addon);
          await installReconciled(
            {
              stage: nextStage,
              selections: nextSelections,
            },
            true,
          );
        } else {
          reconciliationValues = {
            stage: nextStage,
            selections: [],
          };
        }
      } else {
        // We might be at `reconciliationStage[0]` if `installReconciled` was called recursively
        reconciliationValues = {
          stage: reconciliationStages[reconciliationStages.indexOf(stage) || 0],
          selections: [],
        };
      }
    } finally {
      isInstalling = false;
    }
  };
</script>

{@render addonListNav(addonListNavProps)}

{#await prepareReconcile()}
  <CentredPlaceholderText>Loading…</CentredPlaceholderText>
{:then result}
  {#if result?.length}
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
      {#each result as { folders, matches }, idx}
        <li>
          <AddonStub
            bind:selections={reconciliationValues.selections}
            {folders}
            choices={matches}
            {idx}
          />
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
</style>
