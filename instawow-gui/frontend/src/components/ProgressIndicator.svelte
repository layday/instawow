<!-- Adapted from https://css-tricks.com/building-progress-ring-quickly/ -->
<script lang="ts">
  let { diameter, progress } = $props<{
    diameter: number;
    progress: number;
  }>();

  const STROKE = 2;

  let isIndeterminate = $derived(progress === 0);
  let radius = $derived(diameter / 2);
  let circumference = $derived((radius - STROKE) * 2 * Math.PI);
  let offset = $derived(circumference - (isIndeterminate ? 0.75 : progress) * circumference);
</script>

<div
  role="progressbar"
  aria-valuemin={0}
  aria-valuemax={1}
  aria-valuenow={isIndeterminate ? undefined : progress}
>
  <svg height={diameter} width={diameter} viewBox="0 0 {diameter} {diameter}">
    <circle
      r={radius - STROKE}
      cx={radius}
      cy={radius}
      class:indeterminate={isIndeterminate}
      style={`
        stroke-dasharray: ${circumference} ${circumference};
        stroke-dashoffset: ${offset};
        stroke-width: ${STROKE};
      `}
    />
  </svg>
</div>

<style lang="scss">
  svg {
    transform: rotate(-90deg);
  }

  circle {
    transition: stroke-dashoffset 0.35s;
    transform-origin: center;
    fill: transparent;
  }

  .indeterminate {
    animation-duration: 0.75s;
    animation-iteration-count: infinite;
    animation-name: rotate;
  }

  @keyframes rotate {
    from {
      transform: rotate(0);
    }

    to {
      transform: rotate(1turn);
    }
  }
</style>
