## What Changed

Describe the carrier data, claim, schema, tooling, generator, or documentation
change.

## Why

Explain the problem this fixes or the source/evidence behind the change.

## Safety Check

- [ ] I did not include phone numbers, account data, personal passwords,
      private vendor credentials, full IMSI values, full ICCID values, IMEI,
      raw logs, raw bugreports, raw firmware dumps, or private vendor
      responses.
- [ ] If this changes carrier behavior, I included evidence or linked a
      maintained source.
- [ ] If this adds community data, I used a community claim instead of silently
      changing stable generated output.

## Checks

Run the checks that apply:

```bash
python3 tools/validate_community_claims.py community/claims generated/community
python3 tools/test_community_claims.py
python3 tools/validate_public_carrier_data.py carriers generated/index.json
python3 tools/test_generated_android_outputs.py
```
