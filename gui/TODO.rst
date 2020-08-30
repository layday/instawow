- Filtering installed add-ons
- Improve (re)installing 'with options' workflow

  - Resolve add-ons in modal before attempting to (re)install
  - Implement reinstallation in the server rather than have it be
    an ``uninstall`` followed by an ``install`` (cf. atomicity)

- WeakAuras integration

  - Might need to rethink ``strategy_vals`` -
    attach account to options using custom strategy?

- App settings?  Do we need them or can we rely on profiles?
- Tests, tests, tests
