*instawow*
==========

*instawow* is a package manager for World of Warcraft, written
in Python.  It can be used to install, remove and update add-ons from
WoWInterface, CurseForge and Tukui.

Installation
------------

It is recommended to install *instawow* in an isolated environment.
One option is to use `pipx <https://github.com/pipxproject/pipx>`__::

    pipx install instawow

Installing with `pip` is also supported::

    pip3 install instawow

Getting started
---------------

*instawow* is able to interpret add-on URLs, slugs and IDs.
All of the following will install Molinari::

    instawow install https://www.curseforge.com/wow/addons/molinari
    instawow install curse:molinari
    instawow install curse:20338
    instawow install https://www.wowinterface.com/downloads/info13188-Molinari.html
    instawow install wowi:13188

* The ``update`` and ``remove`` commands work in the same way, and ``update``
  can be run without arguments to update all add-ons.
* You can opt into alpha and beta quality add-ons by
  using the ``strategy`` option on ``install``.  This option is only
  supported by CurseForge.
* Use ``list`` to list add-ons managed by *instawow*; ``list-folders -e`` to
  list unmanaged add-ons; ``info`` to display add-on information,
  ``visit`` to open an add-on homepage in your browser and ``reveal`` to
  open the primary add-on folder in your file manager.
* Non-destructive operations accept partial URIs, e.g.
  ``instawow info moli`` will display information about Molinari.

instafying add-ons
----------------------

*instawow* does not know about add-ons it did not itself install.
The Twitch and Minion clients each use their own, proprietary
fingerprinting algorithm to reconcile add-ons you have installed with add-ons
their respective hosts keep on their servers.  Though the details of their implementation
elude me, *instawow* tries to accomplish something similar by combining a variety
of cues (e.g. folders and TOC entries).  This is not done automatically;
you will need to execute ``instawow reconcile`` to absorb add-ons installed
by other means.

WoW Classic
-----------

*instawow* supports Classic – it will correctly install Classic versions
of add-ons from sources depending on the value of the
``game_flavour`` configuration setting.
What *instawow* does not have is a switch you can flick to go from managing
your retail add-ons to managing your classic add-ons and vice versa.
This was a conscious design decision, the merits of which (I should admit)
are open to debate.  If you are already using *instawow* for retail,
you will need to create a separate profile for Classic.  On Linux, this might be::

    env INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow

For ease of use, you might want to set up an alias.  In your Bash profile, add::

    alias instawow-classic='INSTAWOW_CONFIG_DIR=~/.config/instawow-classic instawow'

You would then be able to invoke *instawow* using ``instawow-classic``.

Additional functionality
------------------------

WeakAuras aura updater
~~~~~~~~~~~~~~~~~~~~~~

*instawow* contains a WeakAuras updater modelled after
`WeakAuras Companion <https://weakauras.wtf/>`__.  To use the updater
and provided that you have WeakAuras installed::

    instawow weakauras-companion build -a <your account name>
    instawow install instawow:weakauras-companion

You will have to rebuild the companion add-on prior to updating
to receive aura updates.  If you would like to check for updates on
every invocation of ``instawow update``, install the
``instawow:weakauras-companion-autoupdate`` variant, exposing your account
name as an env var::

    env WAC_ACCOUNT=<your account name> instawow install instawow:weakauras-companion-autoupdate
    env WAC_ACCOUNT=<your account name> instawow update

You may then choose to bypass the companion add-on simply by ommitting the env var.

Caveats
-------

Searching for add-ons
~~~~~~~~~~~~~~~~~~~~~

*instawow* tries to make installing, updating and removing
add-ons quick and painless for those of us who are
(ever so slightly) proficient with the command line
and do not revel in using bloatware which infringe on our privacy
or inhabiting walled gardens.
It does not try to circumvent add-on portals entirely.

Metadata sourcing
~~~~~~~~~~~~~~~~~

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
API interally in Q2 2019, which we have adopted for our own use.
This is similar to what Minion, the WoWInterface-branded add-on manager, has been
doing for years.  The good people at Tukui provide an API for public use.
*instawow* might break whenever one of our sources introduces
a change to their website or API (though only temporarily).

Related work
------------

The author of *wowman* maintains a list of similar software in their
`comrades.csv <https://github.com/ogri-la/wowman/blob/develop/comrades.csv>`__.

Contributing
------------

Bug reports and fixes are welcome.  Do open an issue before committing to
making any significant changes.
