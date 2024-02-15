<script lang="ts">
  import {
    faArrowAltCircleLeft,
    faArrowAltCircleRight,
    faTimesCircle,
  } from "@fortawesome/free-solid-svg-icons";
  import { getContext } from "svelte";
  import { fade } from "svelte/transition";
  import { ALERTS_KEY, ANY_PROFILE, type AlertsRef } from "../stores/alerts.svelte";
  import { ACTIVE_PROFILE_KEY, type ActiveProfileRef } from "../stores/profiles.svelte";
  import Icon from "./SvgIcon.svelte";

  const activeProfileRef = getContext<ActiveProfileRef>(ACTIVE_PROFILE_KEY);
  const alertsRef = getContext<AlertsRef>(ALERTS_KEY);

  let combinedAlerts = $derived(
    [
      alertsRef.value[ANY_PROFILE],
      activeProfileRef.value ? alertsRef.value[activeProfileRef.value] : [],
    ]
      .filter(Boolean)
      .flat(),
  );

  let selectedAlertIndex = $state(0);

  $effect(() => {
    combinedAlerts; // Trigger

    selectedAlertIndex = 0;
  });
</script>

{#if selectedAlertIndex in combinedAlerts}
  {@const alert = combinedAlerts[selectedAlertIndex]}

  <div class="alerts-wrapper">
    <div class="alerts" role="alert" transition:fade={{ duration: 200 }}>
      <div class="current-alert">
        <h1>{alert.heading}</h1>
        <p>{alert.message}</p>
      </div>

      <div class="alert-nav">
        <button
          title="previous alert"
          disabled={!(selectedAlertIndex - 1 in combinedAlerts)}
          onclick={() => (selectedAlertIndex -= 1)}
        >
          <Icon icon={faArrowAltCircleLeft} />
        </button>

        <button title="dismiss alerts" onclick={alertsRef.reset}>
          <Icon icon={faTimesCircle} />
        </button>

        <button
          title="next alert"
          disabled={!(selectedAlertIndex + 1 in combinedAlerts)}
          onclick={() => (selectedAlertIndex += 1)}
        >
          <Icon icon={faArrowAltCircleRight} />
        </button>
      </div>
    </div>
  </div>
{/if}

<style lang="scss">
  @use "sass:math";

  @use "scss/vars";

  $line-height: 1.8em;
  $edge-border-radius: math.div($line-height, 4);

  .alerts-wrapper {
    position: fixed;
    left: 0;
    right: 0;
    display: flex;
    justify-content: center;
    margin-top: calc(3rem + 4px);
    z-index: 20;
  }

  .alerts {
    @extend %pop-out;
    max-width: 75vw;
    padding: 0 0.8rem;
    background-color: var(--alert-background-color);
    font-size: 0.8em;
    display: grid;
    grid-template-columns: auto 6rem;
    grid-column-gap: 0.8rem;
    word-break: break-all;
  }

  .current-alert {
    h1 {
      margin-bottom: 0;
    }
  }

  .alert-nav {
    align-self: center;
    justify-self: center;

    button {
      line-height: $line-height;
      margin: 0;
      padding: 0.5em;
      border-radius: $edge-border-radius;
      border: 0;
      transition: all 0.2s;

      &:disabled {
        opacity: 0.5;
      }

      &:hover:not(:disabled) {
        background-color: var(--inverse-color-alpha-05);
      }

      &:focus {
        background-color: var(--inverse-color-alpha-10);
        box-shadow: inset 0 0 0 1px var(--inverse-color-alpha-20);
      }
    }

    :global(.icon) {
      display: block;
      height: 1rem;
      width: 1rem;
      fill: var(--inverse-color);
    }
  }
</style>
