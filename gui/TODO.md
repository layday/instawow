- [ ] Installed add-on filtering
  - Should probably be done client-side
  - Filtering UX: do we add another search box?
    A separate tab for searching?
  - Should filtering and search use the same algorithm?
- [ ] New notification interface - `window.alert`s are horrible
- [x] Improve (re)installing 'with options' workflow
  - [ ] ~~Resolve add-ons in modal before attempting to (re)install~~
    - Got rid of the installation modal and
      resolution has been subsumed under search
  - [ ] ~~Implement reinstallation in the server rather than have it be
    an `uninstall` followed by an `install` (cf. atomicity)~~
    - Expanded `update` to take strategy into consideration
- [ ] WeakAuras Companion integration
  - [ ] Might need to rethink `strategy_vals` -
    attach account to options using custom strategy?
    - Restructured strategy in `Defn`
      but haven't added a WA strategy yet
      which is going to require a migration
- [ ] App settings?  Do we need them or can we rely exclusively on profiles?
- [ ] Tests, tests, tests
  - See https://objectcomputing.com/resources/publications/sett/july-2019-web-dev-simplified-with-svelte
