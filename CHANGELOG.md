## v2.0.0

This is a big release, the biggest one yet actually (again), so big I decided to call it v2 instead of v1.41, but worry not! Upgrading to this version is still as frictionless as always! There are literally too many new big features that I can't pick a single "headline" feature... so you get five instead (in no specific order)!

**The first big headline feature** here is the new tags gallery page, where you can search, sort, view, and manage your tags. It's like the tag search in the Admin Panel but on steroids! Perfect for both you as the admin, and for any visitors (in case you host a public instance).  
**The second headline feature** is that the uploader got a *massive* upgrade; folders can now map to albums, info saved inside or next to your media files is now read and used, the booru importer is more tightly integrated, you can fetch media from other sites (by pasting the direct URL to it), and much more!  
**The third headline feature** is actually a pair of media-related improvements! First, media descriptions can now display Markdown as well as be enlarged in case you have a lot of content in it. Second, you can now set a custom date for media, so you can finally sort by when the art was *made*, not just by when it was *uploaded*!  
**The fourth headline feature** is a huge suite of tag management upgrades!

- **Tag Ratings:** Tags can now have their own ratings, which automatically escalate a post's rating when a higher-rated tag is added. Tags with ratings outside your current filter also get hidden from autocomplete and suggestions, just like media!
- **Tracked Implied Tags:** Tags added to posts through an implication rule are now tracked and can be hidden if need be!
- **Tag Merging & Alias Management:** You can now merge tags into another tag (turning the merged tag(s) into an alias in the process) as well as being able to edit your tag aliases, both directly inside the tag management modal and the new tags gallery!

**The fifth and final headline feature** is that you can now manually reorder both albums and album contents!

Other *very* notable features include big improvements to tag suggestions and autocomplete, and media thumbnails now being smaller in file size while supporting transparency AND being higher quality (hovering a GIF's thumbnail will now play the GIF too!). There are also new post navigation buttons (with nice little previews of the media you are about to view), a bunch of new keyboard shortcuts (with a new keybinding editor in the Account tab in the Admin Panel!), a new light theme, and the option to blur explicit thumbnails.

Under the hood, there is a brand-new algorithm (TF-IDF, for those curious) for finding related posts that is significantly more accurate while also being faster (and is also customizable!!). The AI tag predictor also got a big upgrade with better management, a new best model (PixAI), and support for hardware acceleration (only supporting CUDA for now, though)! The booru importer now supports importing from Shimmie, Szurubooru, Philomena, and even Blombooru itself. You can even configure a proxy (HTTP or SOCKS) for the direct web fetcher and booru importer in case your instance is hosted somewhere that blocks such sites!

Aside from those features, you can now set explicit permission levels for API keys, so you no longer need to give e.g., external booru viewer applications full admin-level access. Three new sorting options have also been added (custom date, random, and tag count), and the sorting UI is now more compact than ever! I also went and added a "Back to Album" button for when you are viewing media in an album, so you don't need to use the browser's back button anymore. Building on the album changes, I also made the related media and media hierarchy sections more album-friendly!

**You can easily migrate your old thumbnails and previously web-incompatible media to the new thumbnail and web-compatible formats directly in the Admin Panel!** The same goes for the tag implication and alias additions, all can be migrated with a few clicks :)

As for all the bug fixes, security hardening and such, there was a lot. A *lot* of invisible work too, since basically the whole codebase was refactored... The most important two fixes being a completely revamped backup system since it didn't work at all last release (I am really sorry about that..), and that "full backup"s were actually NOT full backups. But now they are! You might want to update to this version before making any more backups. There have been a lot of important security fixes, so I recommend updating just for that.  
Some of the smaller fixes include fewer network requests in nearly all parts of Blombooru, fixed downloads for large media, the usual fixed styling inconsistencies and stray hardcoded strings, and *many* more that are not worth mentioning here.

Oops this went on for way too long... Anyway, I hope you enjoy Blombooru v2.0.0!

## v1.40.1

This is by far the largest release in the history of Blombooru (sarcasm), fixing a grand total of two bugs. The first one being that scrolling inside the bulk tag editor modals was completely broken, and the second one being a resource leak that could leave orphaned media cache files lying around.

## v1.40.0

This is the biggest release yet, with the headline feature being custom CSS themes, custom background support, and easier logo customization! I know I know, it sounds like this is a theming-focused release, but no, it is actually much more than that! I've also gone and made it so you can update existing posts with new media!

Other notable, but not headline-worthy features include tag editing and a new bulk media rating editor. The AI tag predictor settings have also been moved to the Admin Panel (where they belong), making them persistent and adding tag blacklisting in the process.

Tag implications now also support wildcards, so you no longer have to create 100 separate implication rules for a single concept or series or whatever! You can now also make the "Popular Tags" section in the sidebar show the most popular related tags *globally*, not just from the page you are viewing. There is now also a dedicated 404 page in case you somehow wander into the unknown in your Blombooru instance!

In case you need to know some basic info about your instance without needing to log in, you can use the all-new instance info endpoint which displays public good-to-know information about your instance. Perfect for those who are creating clients or tools that interact with Blombooru's internal API!

There have been several performance improvements for this release, the notable ones being that the media uploader now is more than twice as fast than the previous version, and that database connections are held for much shorter durations when serving media.

The bug fixes include the usual styling inconsistencies and untranslated strings. But also more notably, media serving for large media files has been fixed, handling for fullscreen videos has been fixed, and a more smaller/more technical bugs.

This release also addresses the first security advisory Blombooru has received, fixing an SSRF and redirect vulnerability in the Booru importer's image proxy endpoint ([CVE-2026-57448](https://github.com/mrblomblo/blombooru/security/advisories/GHSA-5c5w-x8jp-fjqw))!
