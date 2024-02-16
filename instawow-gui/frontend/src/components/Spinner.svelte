<script lang="ts">
  import ProgressIndicator from "./ProgressIndicator.svelte";
</script>

<div class="spinner">
  <ProgressIndicator diameter={18} progress={0} />
</div>

<style lang="scss">
  .spinner {
    height: 18px;
    line-height: 18px;
    margin: 0 0.5rem;

    :global(circle) {
      stroke: currentColor;
    }
  }
</style>
