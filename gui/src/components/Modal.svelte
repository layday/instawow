<script lang="ts">
  import { fade } from "svelte/transition";

  export let show: boolean;

  const adjustPosition = (el: HTMLElement) => {
    const addonList = el.parentElement.querySelector(".addon-list") as HTMLElement;
    const scrollOfset = addonList.getBoundingClientRect().y;
    const staticOffset = (addonList.offsetParent as HTMLElement).offsetTop + addonList.offsetTop;
    el.style.top = `${Math.floor(Math.abs(scrollOfset - staticOffset))}px`;
    return { destroy: () => {} };
  };

  const dismissOnEsc = () => {
    const handler = (e) => e.key === "Escape" && (show = false);
    document.body.addEventListener("keydown", handler);
    return {
      destroy: () => document.body.removeEventListener("keydown", handler),
    };
  };
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
  transition:fade={{ duration: 200 }}
  use:adjustPosition
  use:dismissOnEsc
  on:click={() => (show = false)}>
  <slot />
</div>
