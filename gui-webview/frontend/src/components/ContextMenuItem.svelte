<script lang="ts">
  export let divider: boolean = false;
</script>

<li class:divider on:click|stopPropagation>
  {#if divider}
    <hr />
  {:else}
    <slot />
  {/if}
</li>

<style lang="scss">
  @import "scss/vars";

  li {
    padding: 0 0.8rem;
    line-height: 1.2rem;

    &:not(.divider):hover {
      background-color: $action-button-bg-color;
      color: $action-button-text-color;
    }

    hr {
      border: 1px solid var(--inverse-color-alpha-20);
    }
  }
</style>
