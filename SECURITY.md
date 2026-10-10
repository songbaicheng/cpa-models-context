# Security

This is native code loaded into the host process, not a sandbox. Only install
libraries from trusted sources and build for the intended host. Incorrect ABI
pointers or a compromised plugin can crash or compromise the host. There is no
network or response-debugging feature in this plugin.

For suspected vulnerabilities, contact the maintainer using a private channel
listed on the repository owner's GitHub profile before opening a public issue.
If no private contact is available, open an issue requesting one **without**
exploit details or sensitive data. No response-time SLA is promised. Include the
plugin version, host version/architecture/libc, and a sanitized reproduction.
Do not publish tokens, private host addresses, or real response payloads.

Review fixes against the latest source; no maintained backport branch or formal
security-audit claim is provided. Token mappings are operator assertions and
must not be treated as authorization or capacity enforcement.
