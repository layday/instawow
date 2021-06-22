*instawow*
==========

.. image:: https://img.shields.io/matrix/wow-addon-management:matrix.org
   :target: https://matrix.to/#/#wow-addon-management:matrix.org?via=matrix.org
   :alt: Matrix channel

*instawow* is a package manager for World of Warcraft.
It can be used to install, remove and update add-ons from
WoWInterface, CurseForge, Tukui and GitHub.

*instawow* tries to make installing, updating and removing
add-ons quick and painless for those of us who are
(ever so slightly) proficient with the command line
and do not revel in using bloatware which infringe on our privacy
or inhabiting walled gardens.

Indi-co-depedently, an *instawow* GUI is in early development.
The GUI does not have feature parity with the CLI and is not particularly,
rigorously, tested.  However, it does offload add-on management to
the *instawow* core.

Some of the features of *instawow* are:

- Interoperable CLI and GUI
- Fuzzy search with download scoring, backed by a catalogue which
  combines add-ons from WoWInterface, CurseForge, Tukui and Townlong Yak
- Ability to interpret add-on URLs and host IDs
- Add-on reconciliation which works with all three major hosts
- Rollback – ability to revert problematic updates
- Multiple update channels – 'stable', 'latest', and alpha and beta
  for CurseForge add-ons
- Dependency resolution on installation
- Version pinning of CurseForge and GitHub add-ons
- Wago integration – a WeakAuras Companion clone which can be managed like
  any other add-on

.. figure:: https://asciinema.org/a/8m36ncAoyTmig4MXfQM8YjE6a.svg
   :alt: Asciicast demonstrating the operation of instawow
   :target: https://asciinema.org/a/8m36ncAoyTmig4MXfQM8YjE6a?autoplay=1
   :width: 640

.. figure:: https://raw.githubusercontent.com/layday/instawow/main/gui-webview/screenshots/v0.6.0_640px.png
   :target: https://github.com/layday/instawow/releases/latest
   :alt: The instawow GUI's main window

Installation
------------

You can download pre-built binaries of *instawow* from GitHub:

- `Binaries <https://github.com/layday/instawow/releases/latest>`__

If you'd prefer to install *instawow* from source, you are able to choose from:

- `pipx <https://github.com/pipxproject/pipx>`__:
  ``pipx install instawow`` or ``pipx install instawow[gui]`` for the GUI
- The `AUR <https://aur.archlinux.org/packages/instawow/>`__
  for Arch Linux:
  ``yay -S instawow``
- Vanilla pip:
  ``python -m pip install -U instawow`` or ``python -m pip install -U instawow[gui]`` for the GUI

Getting started
---------------

tl;dr
~~~~~

Begin by running ``instawow reconcile``
to register previously-installed add-ons with *instawow*
(``instawow reconcile --auto`` to do the same without user input).
To install add-ons, you can search for them using the ``search`` command::

    instawow search molinari

In addition, *instawow* is able to interpret add-on URLs and *instawow*-specific
URNs of slugs and host IDs.
All of the following will install Molinari from CurseForge::

    instawow install https://www.curseforge.com/wow/addons/molinari
    instawow install curse:molinari
    instawow install curse:20338

You can ``update`` add-ons and ``remove`` them just as you'd install them.
If ``update`` is invoked without arguments, it will update all of your
installed add-ons.  You can ``list`` add-ons and view detailed information about
them using ``list --format detailed``.
For ``list`` and similarly non-destructive commands, the source can be omitted
and the slug can be abbreviated, e.g. ``instawow reveal moli``
will open the Molinari add-on folder in your file manager.

Reconciling add-ons
~~~~~~~~~~~~~~~~~~~

*instawow* does not know about add-ons it did not itself install.
The Twitch and Minion clients each use their own, proprietary
fingerprinting algorithm to reconcile add-ons you have installed with add-ons
their respective hosts keep on their servers.  Though the details of their implementation
elude me, *instawow* tries to accomplish something similar by combining a variety
of cues (e.g. folders and TOC entries).
This is not done automatically for you – *instawow* makes a point of
not automatically assuming ownership of your add-ons or your preference
of add-on host.
However, you can run ``reconcile`` in promptless mode with the ``--auto`` flag,
and *instawow* will prioritise add-ons from CurseForge because: (a) they
see more frequent updates; and (b) the API is of a higher quality.
Reconciled add-ons are reinstalled because it is not possible to reliably
determine the installed version; consequently, it would not be possible to offer
updates reliably.

Searching for add-ons
~~~~~~~~~~~~~~~~~~~~~

*instawow* comes with a rudimentary ``search`` command
with results ranked based on edit distance.
Search uses a collated add-on catalogue internally which is updated
`once daily <https://github.com/layday/instawow-data/tree/data>`__.
You can install multiple add-ons directly from search.

Dealing with pesky updates
~~~~~~~~~~~~~~~~~~~~~~~~~~

*instawow* keeps a log of all versions of an add-on it has previously
installed.
Add-on updates can be undone using the ``instawow rollback`` command.
Add-ons which have been rolled back are pinned and will not receive updates.
Rollbacks can themselves be undone with ``instawow rollback --undo``,
which will install the latest version of the specified add-on using
the ``default`` strategy.

Rollback is not supported for WoWInterface and Tukui.

GitHub as a source
~~~~~~~~~~~~~~~~~~

*instawow* supports WoW add-ons *released* on GitHub; that is to say,
the repository must have had a release
– tags are not sufficient – and the release *must*
have a ZIP file attached to it as an asset.
*instawow* will not install or build add-ons directly from
source, or from tarballs or 'zipballs'.
Futhermore, *instawow* will not validate the contents of the ZIP file.
I do not recommend using GitHub as a source unless an add-on cannot
be found on one of the supported add-on hosts.

WoW Classic and *instawow* profiles
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

*instawow* supports Classic – it will correctly install Classic versions
of multi-flavour add-ons provided that the ``game_flavour``
setting is set to ``classic``.
Assuming your default profile is configured for Retail,
you can create a pristine profile for Classic by running::

    instawow -p classic configure

You can create profiles for other versions of the game (e.g. PTR or beta)
in the same way.
You must prefix ``-p <profile>`` to *instawow* commands
to manage each respective profile.

The ``any_flavour`` strategy can be used to install add-ons from CurseForge
which do not have Classic releases but are known to work just as well::

    instawow -p classic install -s any_flavour https://www.curseforge.com/wow/addons/colorpickerplus


Additional functionality
------------------------

WeakAuras aura updater
~~~~~~~~~~~~~~~~~~~~~~

*instawow* contains a WeakAuras updater modelled on
`WeakAuras Companion <https://weakauras.wtf/>`__.  To use the updater
and provided that you have WeakAuras installed::

    instawow weakauras-companion build
    instawow install instawow:weakauras-companion

You will have to rebuild the companion add-on prior to updating
to receive aura updates.  If you would like to check for updates on
every invocation of ``instawow update``, install the
``instawow:weakauras-companion-autoupdate`` variant::

    instawow install instawow:weakauras-companion-autoupdate
    instawow update

Plug-ins
~~~~~~~~

*instawow* can be extended using plug-ins.  Plug-ins can be used to add support
for arbitrary hosts and add new commands to the CLI.  You will find a sample
plug-in in ``tests/plugin``.

Metadata sourcing
-----------------

Originally, *instawow* relied on the official feeds provided by Curse.
Curse retired the feeds in June 2018 and – for a period – *instawow* would
scrape the CurseForge website.  The alternative would have been to use the
old XML-like API.  Because the API was not built for third-party use, it had not been
isolated from user accounts (cf. GitHub integrations).
If users were to log into the API, *instawow* would acquire full
access to their account.  Authentication was also complicated
by the ongoing Curse account migration to Twitch and is (or should be)
unnecessary for the simple use case of installing and updating add-ons.
Thankfully, Twitch migrated to an unauthenticated
API interally in the second quarter of the year of the periodic table,
which we have adopted for our own use.
This is similar to what Minion, the WoWInterface-branded add-on manager, has been
doing for years.  The good people at Tukui provide an API for public use.
*instawow* might break whenever one of our sources introduces
a change to their website or API (though only temporarily).

Remote hosts
------------

Web requests initiated by *instawow* can be identified by its user agent string.

When installing, updating or searching for add-ons, *instawow* will retrieve
add-on metadata from https://raw.githubusercontent.com,
https://addons-ecs.forgesvc.net, https://api.mmoui.com, https://www.tukui.org,
https://hub.wowup.io, https://api.github.com and https://data.wago.io,
and will follow download URLs found in metadata.

Every 24 hours, on launch, *instawow* will query PyPI (https://pypi.org) –
the canonical Python package repository – to check for *instawow* updates.

Related work
------------

The author of `strongbox <https://github.com/ogri-la/strongbox>`__ has been cataloguing similar software
`here <https://ogri-la.github.io/wow-addon-managers/>`__.  If you are unhappy
with *instawow*, you might find one of these other add-on managers more
to your liking.

Contributing
------------

Bug reports and fixes are welcome.  Do open an issue before committing to
making any significant changes.
