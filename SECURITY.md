# Security And Privacy

Do not open a public issue containing credentials, signed vendor URLs, private
carrier responses, account data, phone numbers, full IMSI or ICCID values,
IMEI, serial numbers, raw logs, or raw bugreports.

For a security or privacy issue, use GitHub's private vulnerability reporting
for this repository. For ordinary incorrect carrier data, use the guided public
issue forms after removing private information.

Carrier-data pull requests are treated as untrusted input. Validation checks
the schema, blocks common private-data patterns, computes claim risk and stable
conflicts, and prevents community claims from silently changing stable output.
