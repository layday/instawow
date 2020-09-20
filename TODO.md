CLI
---

- [x] Use `update` method for rollback as opposed to reinstalling now
  that it's an option
- [ ] Allow passing `--strategy` to search?
- [ ] Scoop package for Windows?  brew for Mac?  I don't like Homebrew though.
- [ ] RH/Fedora blocker: https://github.com/indygreg/PyOxidizer/issues/283

GUI
---

- [-] Better RPC error handling
- [ ] New notification interface - `window.alert`s are horrible
- [x] Deleting profiles
  - [ ] ~~Renaming profiles? Meh~~
    - WONTDO
- [ ] Report add-on download progress
  - Investigate JSON-RPC subscriptions
- [ ] Installed add-on filtering
  - Should probably be done client-side
  - Filtering UX: do we add another search box?
    A separate tab for searching?
  - Should filtering and search use the same algorithm?
- [ ] ~~Advanced search with sub-queries (maybe)~~
  - WONTDO
- [x] Improve (re)installing 'with options' workflow
  - [ ] ~~Resolve add-ons in modal before attempting to (re)install~~
    - Got rid of the installation modal and
      resolution has been subsumed under search
  - [ ] ~~Implement reinstallation in the server rather than have it be
    an `uninstall` followed by an `install` (cf. atomicity)~~
    - Expanded `update` to take strategy into consideration
  - Should people be able to subscribe to a new strategy without having
    to reinstall the add-on if the version is the same between the installed
    and new strategy?  This would be similar to 'pinning'
    - Probably not worth the effort
- [ ] WeakAuras Companion integration
  - [ ] Might need to rethink `strategy_vals` -
    attach account to options using custom strategy?
    - Restructured strategy in `Defn`
      but haven't added a WA strategy yet
      which is going to require a migration
- [ ] Duplicate all of the buttons and controls in the menu bar
- [ ] Tests, tests, tests
  - See https://objectcomputing.com/resources/publications/sett/july-2019-web-dev-simplified-with-svelte
- App settings?  Do we need them or can we rely exclusively on profiles?

Both
----

- [ ] Improve test coverage
- [ ] Vendor catalogue?
- [x] Remove really old add-ons from catalogue/search?
- [ ] Categorise WoWI add-ons by compatibility?
  - Though add-ons from CF are prioritised before WoWI we don't want
    reconciliation to work off add-ons of the opposite flavour
- [ ] Cache management - use eviction policy or periodically prune cache.
  Cached (and deleted!) add-ons gradually build up in $TMPDIR.
  I chose $TMPDIR for caching so I could delegate clean-up to the OS but the
  majority of Linuxes only do this on reboot.  Not urgent but I should look
  into it eventually
  - Consider using a more sophisticated caching mechanism
- [x] Precompute normalised add-on names for search
