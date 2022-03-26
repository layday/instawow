<!-- Adapted from https://css-tricks.com/building-progress-ring-quickly/ -->
<script lang="ts">
  export let diameter: number, progress: number;

  const radius = diameter / 2;
  const stroke = 2;
  const circumference = (radius - stroke) * 2 * Math.PI;

  $: indeterminate = progress === 0;
  $: offset = circumference - (indeterminate ? 0.75 : progress) * circumference;
</script>

<div
  role="progressbar"
  aria-valuemin={0}
  aria-valuemax={1}
  aria-valuenow={indeterminate ? undefined : progress}
>
  <svg height={diameter} width={diameter} viewBox="0 0 {diameter} {diameter}">
    <circle
      r={radius - stroke}
      cx={radius}
      cy={radius}
      class:indeterminate
      style={`
        stroke-dasharray: ${circumference} ${circumference};
        stroke-dashoffset: ${offset};
        stroke-width: ${stroke};
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
