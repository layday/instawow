<!-- Adapted from https://css-tricks.com/building-progress-ring-quickly/ -->
<script lang="ts">
  export let diameter: number, progress: number;

  const radius = diameter / 2;
  const stroke = diameter / 8;
  const circumference = (radius - stroke) * 2 * Math.PI;

  $: indeterminate = progress === 0;
  $: offset = circumference - (indeterminate ? 0.75 : progress) * circumference;
</script>

<div
  role="progressbar"
  aria-valuemin="0"
  aria-valuemax="1"
  aria-valuenow={indeterminate ? null : progress.toString()}
>
  <svg height={diameter} width={diameter} viewBox="0 0 {diameter} {diameter}" class:indeterminate>
    <circle
      r={radius - stroke}
      cx={radius}
      cy={radius}
      style={`
        stroke-dasharray: ${circumference} ${circumference};
        stroke-dashoffset: ${offset};
        stroke-width: ${stroke};
      `}
    />
  </svg>
</div>

<style lang="scss">
  circle {
    transition: stroke-dashoffset 0.35s;
    transform: rotate(-90deg);
    transform-origin: 50% 50%;
    fill: transparent;
  }

  .indeterminate {
    animation: 0.75s linear 0s infinite normal none running rotate;
  }

  @keyframes rotate {
    to {
      transform: rotate(1turn);
    }
  }
</style>
