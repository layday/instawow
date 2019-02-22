*instawow*
==========

*instawow* is a package manager for World of Warcraft written
in Python.  It can be used to install, remove and update add-ons from
Curse, WoWInterface and Tukui.

Installation
------------

It is recommended to install *instawow* in an isolated environment.
One option is `pipx <https://github.com/pipxproject/pipx>`__::

    pipx install instawow

Installing with `pip` is also supported::

    pip3 install instawow

Usage
-----

You can install add-ons by their Curse project ID or slug, or their
WoWInterface ID, or even by their URL. All of the following will install
Molinari::

    instawow install curse:20338
    instawow install curse:molinari
    instawow install https://www.curseforge.com/wow/addons/molinari
    instawow install https://wow.curseforge.com/projects/molinari
    instawow install wowi:13188
    instawow install https://www.wowinterface.com/downloads/info13188-Molinari.html

By default *instawow* will install the latest file to have been
*released*. You may also install the latest file that has been
uploaded (be it stable, or beta or alpha quality) by
passing ``--strategy=latest``. This option only affects CurseForge packages.

You can uninstall add-ons with::

    instawow remove <add-on>

You can update all of your add-ons in one go with::

    instawow update

... or any individual add-on the same way you'd install or remove it::

    instawow update <add-on>

You can list installed add-ons with ``instawow list installed``,
outdated add-ons with ``instawow list outdated`` and add-ons that
predate the venerable *instawow* with ``instawow list preexisting``.
``preexisting`` will attempt to extract Curse and WoWI IDs from TOC files
to put you on a path towards instalightment.

To get the full list of available commands, run ``instawow``.

Goodies
-------

BitBar plug-in
~~~~~~~~~~~~~~

*instawow* ships with a `BitBar <https://getbitbar.com/>`__ plug-in
for macOS, which you can use to update add-ons from the menu bar.
To install the plug-in run ``instawow extras bitbar install``.

WeakAuras aura updater
~~~~~~~~~~~~~~~~~~~~~~

*instawow* contains a WeakAuras updater modelled after
`WeakAuras Companion <https://weakauras.wtf/>`__.  To use the updater
and provided that you have WeakAuras installed::

    instawow extras weakauras build-companion
    instawow install instawow:weakauras-companion

Building the companion add-on is expensive, which is why the operation
is not baked into the normal workflow.  (For reference, parsing WeakAuras'
saved variables takes about 15 seconds on my machine.)
Therefore you will have to run ``instawow extras weakauras build-companion`` prior to
``instawow update`` to receive aura updates.

Caveats
-------

Auto-detection
~~~~~~~~~~~~~~

*instawow* has no way to know about add-ons it did not itself install.
The Twitch (née Curse) client uses a proprietary fingerprinting algorithm
to reconcile add-ons installed locally with add-ons they keep on their servers.
Even if the fingerprint had been reverse-engineered, I'd be loath to adopt it.
Ideologically, because it was born of a desire to monopolise the add-on distribution
market; and, practically, because we could never know when Curse might pull
the rug from under our feet.
The Minion app also implements a similar though less sophisticated
fingerprinting technique.

Metadata harvesting
~~~~~~~~~~~~~~~~~~~

The Twitch client uses a closed metadata API internally.
Because the API was not built for third-party use it has not been
isolated from user accounts (cf. GitHub integrations).
If users were to log into the API *instawow* would acquire full
access to their account. Authentication is also complicated
by the ongoing Curse account migration to Twitch and is (or should be)
unnecessary for the simple use case of installing and updating add-ons.
Until recently *instawow* used to rely on the official feeds.
These were apparently sunsetted by Curse on 8 June 2018, leaving us with
no choice but to scrape the website.
Scraping is a delicate art.  The slightest variation in the HTML output
might very easily trip up *instawow* and the code will need to be updated
whenever Curse decide to change parts of *their* code.
By contrast Minion uses an undocumented but open JSON API, which
*instawow* does communicate with.  Tukui provides an API for public use.

Discovery
~~~~~~~~~

*instawow*'s purpose is to facilitate add-on management and not discovery.
It does not seek to drive people away from add-on portals; but to make
installing, updating and removing add-ons found on portals hassle-free
for those of us who are (ever so slightly) proficient with the command
line and do not particularly revel in using bloatware or inhabiting
walled gardens.  It is also important to note that the Twitch client
communicates with Google Analytics, Scorecard Research and Nielsen
without user consent, which is unacceptable to me and my European
brethren.

Development
-----------

Fork and clone the `repo <https://github.com/layday/instawow>`__, ``cd``
and::

    python3 -m venv venv
    source venv/bin/activate
    python3 -m pip install -e .

Happy hacking.

Contributing
------------

Bug reports and fixes are welcome. Do open an issue before committing to
making any significant changes.
