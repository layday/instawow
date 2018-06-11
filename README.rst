*instawow* is a fledgling package manager for World of Warcraft written
in Python. It can be used to install, remove and update add-ons from
Curse, WoWInterface and Tukui.

Installation
------------

Assuming you have Python 3.6 or higher::

    pip3 install instawow

Usage
-----

Installing add-ons
~~~~~~~~~~~~~~~~~~

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
passing ``--strategy=latest``. This option only applies to CurseForge packages.

Updating
~~~~~~~~

You can update all of your add-ons in one go with ``instawow update`` or
any individual add-on the same way you'd install or remove it:
``instawow update <add-on>``.

Uninstalling
~~~~~~~~~~~~

Uninstalling an add-on is as simple as ``instawow remove <add-on>``.

Other operations
~~~~~~~~~~~~~~~~

You may list installed add-ons with ``instawow list installed``;
outdated add-ons with ``instawow list outdated``; and pre-existing
add-ons with ``instawow list preexisting``. The latter command will
attempt to reconcile add-on folders with their corresponding Curse IDs,
where available.

To see information about an installed add-on, execute
``instawow info <add-on>``. To visit its homepage, execute
``instawow hearth <add-on>``. And to open its main folder in your file
manager, run ``instawow reveal <add-on>``.

Goodies
-------

*instawow* ships with a `BitBar <https://getbitbar.com/>`__ plug-in
for macOS, which you can use to update add-ons from the menu bar.
To install the plug-in run ``instawow extras bitbar install``.

Caveats
-------

Auto-detection
~~~~~~~~~~~~~~

*instawow* will only manage add-ons it itself installed
because it has no registry from which to derive add-on fingerprings.
The Twitch (née Curse) client uses a proprietary fingerprinting algo
that nobody (that I know) has been able to figure out how is calculated.
Even if the fingerprint had been reverse-engineered, I'd be loath to adopt it.
Ideologically because it was born of a desire to monopolise the add-on distribution
market and practically because we could never know when Curse might pull
the rug from under our feet. WoWI's Minion app also
implements a similar though less sophisticated fingerprinting technique.

Metadata extraction
~~~~~~~~~~~~~~~~~~~

The Twitch client uses a closed metadata API internally.
Because the API was not built for third-party use it has not been
isolated from user accounts (cf. GitHub integrations).
If users were to log into the API *instawow* would acquire full
access to their account. Authentication is also complicated
by the ongoing Curse account migration to Twitch and is (or should be)
unnecessary for the simple use case of installing and updating add-ons.
Until recently *instawow* used to rely on the official feeds.  These
were apparently sunsetted by Curse on 8 June 2018,
completing the migration to the internal API, leaving us with
no choice but to scrape CurseForge pages.

By contrast Minion uses an undocumented but open JSON API, which
*instawow* does communicate with.
Because it has a much shorter execution cycle than a desktop app,
*instawow* caches (some) add-on metadata for one hour. If you do for whatever
reason need to force an early resync you can do so with
``instawow debug cache invalidate``.

Discovery
~~~~~~~~~

*instawow* aims to facilitate add-on management and not discovery. It
does not seek to drive users away from add-on portals; but to make
installing, updating and removing add-ons found on portals hassle-free
for those of us who are (ever so slightly) proficient with the command
line and do not particularly relish in using bloatware or inhabiting
walled gardens.  It is also important to note that the Twitch client
communicates with Google Analytics, Scorecard Research and Nielsen
without user consent, which is unacceptable to me and my European
brethren.

Development
-----------

Fork and clone the `repo <https://github.com/layday/instawow>`__, ``cd``
and::

    python3 -m venv venv
    source venv/bin/active
    python3 -m pip install -e .

Happy hacking.

Contributing
------------

Bug reports and fixes are welcome. Do open an issue before committing to
making any significant changes.
