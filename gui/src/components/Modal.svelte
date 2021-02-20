<script lang="ts">
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";

  export let show: boolean, addonListEl: HTMLElement;

  let wrapperEl: HTMLElement;

  const adjustPosition = () => {
    const scrollOfset = addonListEl.getBoundingClientRect().y;
    const staticOffset =
      (addonListEl.offsetParent as HTMLElement).offsetTop + addonListEl.offsetTop;
    wrapperEl.style.top = `${Math.floor(Math.abs(scrollOfset - staticOffset))}px`;
  };

  const dismissOnEsc = (node: HTMLElement) => {
    const handler = (e: KeyboardEvent) => e.key === "Escape" && (show = false);
    document.body.addEventListener("keydown", handler);
    return {
      destroy: () => document.body.removeEventListener("keydown", handler),
    };
  };

  onMount(adjustPosition);
</script>

<div
  class="modal-wrapper"
  bind:this={wrapperEl}
  transition:fade={{ duration: 200 }}
  use:dismissOnEsc
  on:click={() => (show = false)}
>
  <slot />
</div>

<style lang="scss">
  .modal-wrapper {
    position: absolute;
    left: 0;
    right: 0;
    height: 101%; /* leeway for position adjustment */
    z-index: 10;
    display: flex;
    background-color: var(--base-color-alpha-65);
  }
</style>
