<script context="module" lang="ts">
  export type Alert = {
    heading: string;
    message: string;
  };
</script>

<script lang="ts">
  import {
    faArrowAltCircleLeft,
    faArrowAltCircleRight,
    faTimesCircle,
  } from "@fortawesome/free-solid-svg-icons";
  import { fade } from "svelte/transition";
  import Icon from "./SvgIcon.svelte";

  export let alerts: Alert[];

  let alertIndex = 0;

  const resetAlerts = () => {
    alerts = [];
    alertIndex = 0;
  };

  $: alert = alerts[alertIndex];
</script>

{#if alert}
  <div class="alerts-wrapper">
    <div class="alerts" transition:fade={{ duration: 200 }}>
      <div class="current-alert">
        <h1>{alert.heading}</h1>
        <p class="message">{alert.message}</p>
      </div>
      <div class="alert-nav">
        <button
          title="previous alert"
          disabled={!(alertIndex - 1 in alerts)}
          on:click={() => (alertIndex -= 1)}
        >
          <Icon icon={faArrowAltCircleLeft} />
        </button>
        <button title="dismiss alerts" on:click={() => resetAlerts()}>
          <Icon icon={faTimesCircle} />
        </button>
        <button
          title="next alert"
          disabled={!(alertIndex + 1 in alerts)}
          on:click={() => (alertIndex += 1)}
        >
          <Icon icon={faArrowAltCircleRight} />
        </button>
      </div>
    </div>
  </div>
{/if}

<style lang="scss">
  @use "sass:math";

  $line-height: 1.8em;
  $edge-border-radius: math.div($line-height, 4);

  .alerts-wrapper {
    position: fixed;
    width: 100%;
    left: 0;
    right: 0;
    display: flex;
    justify-content: center;
    margin-top: calc(-0.8rem - 1px);
    z-index: 20;
  }

  .alerts {
    max-width: 75vw;
    padding: 0 0.8rem;
    background-color: var(--alert-background-color);
    -webkit-backdrop-filter: blur(5px);
    backdrop-filter: blur(5px);
    border-bottom-left-radius: 0.25rem;
    border-bottom-right-radius: 0.25rem;
    box-shadow: 0 1rem 3rem var(--inverse-color-alpha-10), inset 0 1px var(--base-color-tone-20);
    font-size: 0.8em;
    display: grid;
    grid-template-columns: auto 6rem;
    grid-column-gap: 0.8rem;
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

  .message {
    word-break: break-all;
  }
</style>
