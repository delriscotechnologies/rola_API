# Security policy

## Supported version

Security fixes are applied to the latest version on the `main` branch.

## Reporting a vulnerability

Use the repository's **Security** tab and **Report a vulnerability** when available. Otherwise, open a minimal issue requesting a private reporting channel without sensitive details.

Include the affected version, operating system, reproduction steps, and impact.

## Intended scope

rola serves music read-only on a trusted network. It has no authentication or built-in HTTPS. Anyone who can reach the server can request its catalog, covers, and audio.

For private cloud access, use a VPN or an HTTPS reverse proxy with authentication. Restrict direct access to port 8000.

## Network access

The launcher listens on all IPv4 interfaces. Setup requests a Windows firewall rule for TCP 8000, Private networks, the local subnet, and the Python executable. This rule is not exclusive to rola; other apps using that interpreter and port may match it. Other firewall rules can allow broader access.

Host validation checks the requested server name, not the client's identity. Restart rola after its IP address changes.

## Music and local files

Keep the repository, runtime files, and music folder under your control. The API validates opened music files against the configured folder and rejects symbolic links, junction traversal, and hard-linked files.

Use trusted MP3s. Catalog scans and media parsing have no strict resource quotas or rate limits; rola is not designed for hostile files or unrestricted public traffic. Logs may contain music filenames and local paths.

## Dependencies

Setup pins direct dependencies, but does not lock every transitive dependency. Rerunning setup is not a guarantee that all installed packages are free of vulnerabilities.
