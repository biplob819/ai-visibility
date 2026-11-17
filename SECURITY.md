# Security policy

## Supported versions

Security fixes go into the latest minor release of citewatch (currently 0.1.x). Older
versions are not patched; please upgrade.

## Reporting a vulnerability

Please **do not** open a public issue for a security problem. Use GitHub's private
vulnerability reporting instead:
<https://github.com/biplob819/ai-visibility/security/advisories/new>.

Include what you found, how to reproduce it, and what an attacker could do with it. You will
get an acknowledgement within 7 days and a plan or a fix within 30 days. We will credit you
in the release notes unless you ask us not to.

Things we especially want to hear about:

- any way to make the fetcher ignore robots.txt, exceed 1 request per second per host, retry
  past a block, fetch a URL that was not cited, or send a different user agent;
- any way an API key could be printed, logged or written to a file;
- any way page HTML or text could end up in a study's committed data or results;
- a crafted provider response, robots.txt, sitemap or page that crashes citewatch, makes it
  write outside the study folder, or makes it spend past its cost cap.

## If citewatch fetched your site badly

If a citewatch fetcher broke the rules in [docs/responsible-use.md](docs/responsible-use.md)
on your site, contact the person running that study through the address in its user agent,
and tell us too, through a private report as above or a public issue if nothing sensitive is
involved. Please include the user agent and the times of the requests.

## Scope

citewatch makes no network calls except to the AI providers configured with your own keys
and to the pages your study's answers cited. It has no server and collects no telemetry.
