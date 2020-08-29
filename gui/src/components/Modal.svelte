<script lang="ts">
  import { onMount } from "svelte";
  import { fade } from "svelte/transition";

  export let show: boolean;

  let wrapperElement: HTMLElement;

  const adjustPosition = () => {
    const addonList = wrapperElement.parentElement.querySelector(".addon-list") as HTMLElement;
    const scrollOfset = addonList.getBoundingClientRect().y;
    const staticOffset = (addonList.offsetParent as HTMLElement).offsetTop + addonList.offsetTop;
    wrapperElement.style.top = `${Math.floor(Math.abs(scrollOfset - staticOffset))}px`;
  };

  const dismissOnEsc = () => {
    const handler = (e) => e.key === "Escape" && (show = false);
    document.body.addEventListener("keydown", handler);
    return {
      destroy: () => document.body.removeEventListener("keydown", handler),
    };
  };

  onMount(adjustPosition);
</script>

<style lang="scss">
  .modal-wrapper {
    position: absolute;
    left: 0;
    right: 0;
    height: 101%; /* leeway for position adjustment */
    z-index: 10;
    display: flex;
    background-color: var(--base-color-65);
  }
</style>

<div
  class="modal-wrapper"
  bind:this={wrapperElement}
  transition:fade={{ duration: 200 }}
  use:dismissOnEsc
  on:click={() => (show = false)}>
  <slot />
</div>
