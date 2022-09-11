*instawow*
==========

.. image:: https://img.shields.io/matrix/wow-addon-management:matrix.org
   :target: https://matrix.to/#/#wow-addon-management:matrix.org?via=matrix.org
   :alt: Matrix channel

*instawow* is an add-on manager for World of Warcraft.
It can be used to install, update and remove add-ons from GitHub,
CurseForge, WoWInterface and Tukui.
*instawow* has an interoperable CLI and GUI, fuzzy search with download scoring
and several other goodies.

.. list-table::
   :widths: 50 50

   * - .. figure:: https://asciinema.org/a/8m36ncAoyTmig4MXfQM8YjE6a.svg
          :target: https://asciinema.org/a/8m36ncAoyTmig4MXfQM8YjE6a?autoplay=1
          :alt: Asciicast demonstrating the operation of instawow
          :width: 640
     - .. figure:: https://raw.githubusercontent.com/layday/instawow/main/gui-webview/screenshots/v1.34.1.png
          :target: https://github.com/layday/instawow/releases/latest
          :alt: instawow-gui main window
          :width: 640

Installation
------------

You can download pre-built binaries of *instawow* from GitHub:

- `Binaries <https://github.com/layday/instawow/releases/latest>`__

If you'd prefer to install *instawow* from source, you are able to choose from:

- `pipx <https://github.com/pipxproject/pipx>`__:
  ``pipx install instawow`` or ``pipx install instawow[gui]`` for the GUI
- Vanilla pip:
  ``python -m pip install -U instawow`` or ``python -m pip install -U instawow[gui]`` for the GUI

CLI operation
-------------

tl;dr
~~~~~

Begin by running ``instawow reconcile``
to register previously-installed add-ons with *instawow*
(or ``instawow reconcile --auto`` to do the same without user input).
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

Add-on reconciliation
~~~~~~~~~~~~~~~~~~~~~

Add-on reconciliation is not automatic – *instawow* makes a point
of not automatically assuming ownership of your add-ons.
However, you can automate reconciliation with ``reconcile --auto``
and *instawow* will prioritise add-ons from CurseForge.
Reconciled add-ons are reinstalled because the installed version cannot be
extracted reliably.

Add-on search
~~~~~~~~~~~~~

*instawow* comes with a rudimentary ``search`` command
with results ranked based on edit distance and popularity.
Search uses a collated add-on catalogue which is updated
`once daily <https://github.com/layday/instawow-data/tree/data>`__.
You can install multiple add-ons directly from search.

Reverting add-on updates
~~~~~~~~~~~~~~~~~~~~~~~~

*instawow* keeps a log of all versions of an add-on it has previously
installed.
Add-on updates can be undone using the ``instawow rollback`` command.
Add-ons which have been rolled back are pinned and will not receive updates.
Rollbacks can themselves be undone with ``instawow rollback --undo``,
which will install the latest version of the specified add-on using
the ``default`` strategy.

Profiles
~~~~~~~~

*instawow* supports multiple game versions by means of profiles.
Assuming your default profile is configured for retail,
you can create a pristine profile for classic with::

    instawow -p classic configure

"``classic``" is simply the name of the profile; you will be asked to select
the game flavour that it corresponds to.  You can have several profiles
of the same flavour (think alpha, beta and PTR).

``-p`` is a global option. You can prefix any *instawow* command with ``-p``.
For instance, to update your Classic add-ons, you would run::

    instawow -p classic update

You can omit ``-p`` for the default profile if one exists.

Migrating Classic profiles
^^^^^^^^^^^^^^^^^^^^^^^^^^

With the exception of "Classic Era" profiles
(``vanilla_classic`` in *instawow* parlance), classic profiles will start
receiving updates for the latest Classic release once it is supported by
*instawow*.  No user intervention is necessary, save for updating *instawow*.

WeakAura updater
~~~~~~~~~~~~~~~~

*instawow* contains a WeakAura updater modelled after
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

CurseForge
~~~~~~~~~~

CurseForge is set to retire its unauthenticated add-on API by the end of Q1 2022.
CurseForge will be issuing keys for the new API conditionally and which
add-on managers are obligated to conceal.
The new API is therefore unworkable for add-on managers except through a
proxy service, which the author of this particular add-on manager cannot afford.
At the same time, CurseForge will be providing the option for authors to unlist
their add-ons from the new API, and downloads intitiated through the new API
will not count towards author credits for the ad revenue sharing programme.

GitHub
~~~~~~

*instawow* supports WoW add-ons *released* on GitHub – that is to say that
the repository must have a release (tags won't work) and the release must
have an add-on ZIP file attached to it as an asset.
*instawow* will not install or build add-ons directly from
source, or from tarballs or 'zipballs', and will not validate
the contents of the ZIP file.

Transparency
------------

Web requests initiated by *instawow* can be identified by its user agent string.

Every 24 hours, on launch, *instawow* will query `PyPI <https://pypi.org>`__ –
the canonical Python package index – to check for *instawow* updates.

Contributing
------------

Bug reports and fixes are welcome.  Do open an issue before committing to
making any significant changes.

Related work
------------

The author of `strongbox <https://github.com/ogri-la/strongbox>`__ has been
cataloguing similar software.  If you are unhappy
with *instawow*, you might find one of these
`other <https://ogri-la.github.io/wow-addon-managers/>`__ add-on managers more
to your liking.
