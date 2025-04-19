Changelog
=========


v6.0.0
------

- Added game version extraction fallback.

  - The ``WeakAurasCompanion`` builder will no longer error
    if it is unable to read the game version from ``.build.info``.

- Added support for the ``trash`` command on macOS.

  - Removed add-on folder will now be trashed.

- Improved reading configuration values from environment variables.

  - Configuration objects will now respect nested environment overrides,
    e.g. ``INSTAWOW_ACCESS_TOKENS_GITHUB``
    will map to ``global_config.access_tokens.github``.

- Fixed caching redirects and failed range requests.
- Dropped support for Python 3.11 and added preliminary support for Python 3.14.

API
~~~

- Removed plug-in accessors from the ``GlobalConfig``.
  This is a breaking change.
- Added ``instawow.config.make_plugin_dirs`` utility function, returning
  a named plug-in's configuration, cache and state directories.
- Made the ``instawow.cli.prompts`` module public for use by plug-ins.

CLI
~~~

- Fixed column alignment for tables containing CJK characters.


v5.0.0
------

- Hard links and symbolic links are now expanded in configuration paths.

API
~~~

- Access tokens can now be sourced by third-party resolvers using the
  ``instawow.resolvers.AccessToken`` decorator.
- ``_resolve_one`` has once again been renamed to ``resolve_one`` on the
  ``instawow.resolvers.Resolver`` interface.
- The active configuration is no longer stored on ``Resolver`` instances;
  it must be retrieved from ``instawow.config_ctx.config`` on demand.
- The active configuration is no longer stored in the ``click`` context object;
  it must be retrieved from ``instawow.config_ctx.config`` on demand.
- The ``instawow.progress_reporting`` module has been made public and can be used
  by plug-ins.

GUI
~~~

- Linux ARM builds are now available.


v4.8.0
------

- Work around WoWI TLS sniffing causing download errors.
- Drop $TMPDIR in preference of the XDG cache dir.

CLI
~~~

- Add new ``cache clear`` command.


v4.7.0
------

- Add env var to override the CurseForge API URL.
- Read access tokens from separate configuration file if present.
- Add workaround for version pinning for CurseForge
  in the pathological case (where version contains an underscore).
- Suppressed intermittent range error from GitHub.
- Extract game version from WoW installation for WA updater.
  The ``WeakAurasCompanion`` add-on's game version will always be up to date.

CLI
~~~

- Allow uninstalling add-ons from unknown sources.
  This can happen if e.g. the source's resolver was unregistered.
- Add ``configure`` command to WA updater for storing the Wago access token.
  Access token migrated from top-level configuration.


v4.6.0
------

- Distinguish between Curse add-on versions with the same display name.
  This will trigger dummy updates for up-to-date add-ons, but the release
  of the prepatch is as good a time as any to have that happen.


v4.5.0
------

- Added pre-release fallback when a GitHub, CurseForge or Wago add-on
  has no stable releases.
- Improved error message when an access token is mandatory and not set.
- Stopped bundling the GUI as part of the *instawow* distribution.


v4.4.2
------

GUI
~~~

- Fixed running the JSON-RPC server on Windows.


v4.4.1
------

- Tweaked database settings.

CLI
~~~

- Fixed generic progress counter.

GUI
~~~

- Granted full disk access to the Linux flatpak.
- Fixed reconciliation skipping to the end.


v4.4.0
------

- Improved Lua parser performance by inlining loops.

GUI
~~~

- Replaced Linux app images with flatpaks.
  Currently, only x64 binaries are precompiled.
- Added build configuration for system-native Linux packages.
- Fixed hang on close on Linux.


v4.3.0
------

CLI
~~~

- Added ``--remote`` option to ``view-changelog`` command to retrieve
  remote add-on changelogs.
- Improved ``search`` command responsiveness.
- Improved install and update progress display.
- Fixed issue with installed add-ons being removed prior to re-reconciled
  add-ons being downloaded.

GUI
~~~

- Fixed start-up command crashing spectacularly.


v4.2.0
------

- Rolled all versions of Classic over to Cataclysm.

CLI
~~~

- Added overall install and update progress.
- Split ``reconcile --installed`` out into a separate ``rereconcile`` command
  which allows filtering add-ons to be re-reconciled.
- Fixed changing an existing profile's flavour.


v4.1.1
------

- Relaxed ``aiohttp`` version constraint.
- Fixed self-update check HTTP cache directory path.


v4.1.0
------

- Extended support for the ``any_flavour`` strategy to GitHub add-ons.
- Changed ``any_flavour`` logic to prioritise add-ons of the same or similar
  flavours.
- Changed default flavour of the Classic PTR to Cataclysm.
- Added support for comma-separated interface versions in add-on TOC files.
- Added support for Python 3.13.
- Made various performance improvements.

CLI
~~~

- Added ``debug config`` and ``debug sources`` sub-commands.
- Added ability to filter add-ons by source in ``view-changelog`` output.


v4.0.0
------

- Added support for the Classic Cataclysm beta.

CLI
~~~

- Relocated plug-in commands under ``plugins``.
- Removed ``--retain-strategies`` flag from ``update`` command.
  Strategies are now always respected when present; to force an update with
  the default strategy set, append ``#=`` to the add-on definition.
- Global ``-d/--debug`` flag renamed to ``-v/--verbose``.
- ``configure --show-active`` sub-flag reimagined as the ``debug`` command.
- Allow filtering installed add-ons by source using ``list source:``, replacing
  "source" with the source identifier.


v3.3.0
------

- Added support for alternative archive openers in plug-ins.
- Reworked HTTP cache.

CLI
~~~

- Extended ``--no-cache`` flag to add-on downloads.


v3.2.0
------

- Added support for Python 3.12.

CLI
~~~

- The CLI is now bundled as a single-file self-extracting
  executable using `PyApp <https://github.com/ofek/pyapp>`_
  instead of PyInstaller.

GUI
~~~

- Fixed creating non-standard configuration directories.
- Stopped bundling Mozilla's root certificate store.


v3.1.0
------

- Reconciliation was made to cross-reference add-ons from the GitHub catalogue.
- XDG env vars are now respected on all platforms; if `$XDG_CONFIG_HOME` is set,
  it will be preferred over the platform-native configuration directory.
  This is a behaviour change on macOS and Windows.
- Logs and plug-in data are stored under `$XDG_STATE_HOME` on Linuxes by default.


v3.0.1
------

CLI
~~~

- Restored asyncio event loop policy override on Windows for Python 3.9.

GUI
~~~

- Fixed add-on alias and URL search.


v3.0.0
------

- Dropped support for Tukui add-ons other than the two headline UI suites,
  having switched from the original API at https://www.tukui.org/api.php
  to https://api.tukui.org/v1.
  The new API is hosted by the author of
  `CurseBreaker <https://github.com/AcidWeb/CurseBreaker>`_.
  The original API is unmaintained and the add-on index has fallen into disuse.
- Numeric aliases are no longer valid for Tukui add-ons; use ``tukui:elvui`` for
  ElvUI and ``tukui:tukui`` for Tukui.

CLI
~~~

- Added WoW installation finder (Mac only).  Located installations will be
  offered as suggestions bypassing manual add-on directory and flavour entry
  when configuring *instawow*.
- Added add-on definition mini-DSL replacing the various strategy install options.
  Strategies can now be passed as URL fragments of the add-on ``Defn``,
  e.g. ``foo:bar#any_flavour,version_eq=1``.
- Strategies passed to ``update --retain-strategies`` will be respected *if* they result
  in a change.  This opens up several possibilities, e.g. a bare ``source:alias``
  will unpin an add-on that was previously rolled back.
- Removed ``--version`` option from ``rollback``.  Use ``update --retain-strategies`` to
  roll back to a known version.
- Added ``--dry-run`` option to ``install`` and ``update``.
  Issue ``instawow update --dry-run`` to check for add-on updates.
- Added ``list-sources`` command to display the active source metadata.
- Added ``--prefer-source`` option to ``search``.  If an add-on is found
  from a preferred source, identical add-ons from other sources are omitted
  from the results.
- Installed add-ons are now excluded from ``search`` results.
  This includes identical add-ons from sources other than the one installed.
  Pass ``--no-exclude-installed`` to opt out.
- Changed the Markdown flavour used to convert changelogs
  with pandoc from Markdown.pl to CommonMark to fix an issue
  with list formatting.

API
~~~

- Public enum members are now capitalised.
- Exposed ``plugins.InstawowPlugin`` protocol.  *instawow* plug-ins should
  conform to this protocol.
